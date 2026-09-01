"""Authenticated activity detail, matching and athlete feedback API."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, status
from pydantic import BaseModel, ConfigDict, Field

from swim_coach.application.services.activity_data import ActivityDetail
from swim_coach.application.services.activity_views import analysis_metrics_v1
from swim_coach.domain.activities import SessionFeedback, WorkoutExecutionMatch
from swim_coach.domain.operations import Job
from swim_coach.domain.shared.errors import ResourceNotFoundError
from swim_coach.domain.shared.value_objects import EntityId
from swim_coach.interfaces.rest.dependencies import (
    Authenticated,
    CsrfAuthenticated,
    RequestCorrelationId,
    Services,
)
from swim_coach.interfaces.rest.schemas import ActivityResponse, SyncJobResponse

router = APIRouter(prefix="/api/v1/activities", tags=["activities"])
IdempotencyHeader = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=200)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IntervalResponse(StrictModel):
    index: int
    interval_type: str
    distance_m: int
    duration_seconds: Decimal
    rest_seconds: Decimal
    pace_seconds_per_100m: Decimal | None
    stroke_type: str | None
    swolf: Decimal | None


class AnalysisResponse(StrictModel):
    version: str
    parser_version: str
    quality: str
    metrics: dict[str, object]
    flags: list[str]


class MatchResponse(StrictModel):
    planned_workout_id: UUID
    method: str
    confidence: Decimal

    @classmethod
    def from_domain(cls, match: WorkoutExecutionMatch) -> MatchResponse:
        return cls(
            planned_workout_id=match.planned_workout_id.value,
            method=match.method,
            confidence=match.confidence,
        )


class FeedbackResponse(StrictModel):
    id: UUID
    rpe: int
    technique_rating: int | None
    fatigue_rating: int | None
    enjoyment_rating: int | None
    pain_present: bool
    pain_location: str | None
    pain_intensity: int | None
    comment: str | None
    version: int
    updated_at: datetime

    @classmethod
    def from_domain(cls, feedback: SessionFeedback) -> FeedbackResponse:
        if feedback.rpe is None:
            raise ValueError("legacy feedback projection requires a manual integer RPE")
        return cls(
            id=feedback.id.value,
            rpe=feedback.rpe,
            technique_rating=feedback.technique_rating,
            fatigue_rating=feedback.fatigue_rating,
            enjoyment_rating=feedback.enjoyment_rating,
            pain_present=feedback.pain_present,
            pain_location=feedback.pain_location,
            pain_intensity=feedback.pain_intensity,
            comment=feedback.comment,
            version=feedback.version,
            updated_at=feedback.updated_at,
        )


class ActivityDetailResponse(StrictModel):
    activity: ActivityResponse
    normalized: bool
    parser_version: str | None
    profile_version: str | None
    quality: str | None
    completeness: Decimal | None
    warnings: list[str]
    intervals: list[IntervalResponse]
    analysis: AnalysisResponse | None
    match: MatchResponse | None
    feedback: FeedbackResponse | None
    raw_fit_exposed: bool = False

    @classmethod
    def from_detail(cls, detail: ActivityDetail) -> ActivityDetailResponse:
        normalized = detail.normalized
        normalization = normalized.normalization if normalized else None
        return cls(
            activity=ActivityResponse.from_domain(detail.activity),
            normalized=normalized is not None,
            parser_version=normalization.parser_version if normalization else None,
            profile_version=normalization.profile_version if normalization else None,
            quality=normalization.quality.value if normalization else None,
            completeness=normalization.completeness if normalization else None,
            warnings=list(normalization.warnings) if normalization else [],
            intervals=(
                [
                    IntervalResponse(
                        index=item.interval_index,
                        # Freeze the v1 vocabulary. Canonical v2 types are
                        # projected through /api/v2/activities instead.
                        interval_type=("rest" if item.interval_type == "rest" else "work"),
                        distance_m=item.distance_m,
                        duration_seconds=item.duration_seconds,
                        rest_seconds=item.rest_seconds,
                        pace_seconds_per_100m=item.pace_seconds_per_100m,
                        stroke_type=item.stroke_type,
                        swolf=item.swolf,
                    )
                    for item in normalized.intervals
                ]
                if normalized
                else []
            ),
            analysis=(
                AnalysisResponse(
                    version=detail.analysis.analysis_version,
                    parser_version=detail.analysis.parser_version,
                    quality=detail.analysis.quality.value,
                    metrics=analysis_metrics_v1(dict(detail.analysis.metrics)),
                    flags=list(detail.analysis.flags),
                )
                if detail.analysis
                else None
            ),
            match=MatchResponse.from_domain(detail.match) if detail.match else None,
            feedback=(
                FeedbackResponse.from_domain(detail.feedback)
                if detail.feedback is not None and detail.feedback.rpe is not None
                else None
            ),
        )


class FeedbackRequest(StrictModel):
    rpe: int = Field(ge=1, le=10)
    technique_rating: int | None = Field(default=None, ge=1, le=5)
    fatigue_rating: int | None = Field(default=None, ge=1, le=5)
    enjoyment_rating: int | None = Field(default=None, ge=1, le=5)
    pain_present: bool = False
    pain_location: str | None = Field(default=None, max_length=120)
    pain_intensity: int | None = Field(default=None, ge=1, le=10)
    comment: str | None = Field(default=None, max_length=2_000)
    version: int | None = Field(default=None, ge=1)


class ManualMatchRequest(StrictModel):
    planned_workout_id: UUID


@router.get("", response_model=list[ActivityResponse])
async def list_activities(
    authenticated: Authenticated,
    services: Services,
) -> list[ActivityResponse]:
    async with services.uow_factory() as uow:
        activities = await uow.activities.list_recent(authenticated.user.id, limit=100)
    return [ActivityResponse.from_domain(item) for item in activities]


@router.get("/{activity_id}", response_model=ActivityDetailResponse)
async def get_activity(
    activity_id: UUID,
    authenticated: Authenticated,
    services: Services,
) -> ActivityDetailResponse:
    detail = await services.activity_data.get(authenticated.user.id, EntityId(activity_id))
    return ActivityDetailResponse.from_detail(detail)


@router.post(
    "/{activity_id}/process",
    response_model=SyncJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def process_activity(
    activity_id: UUID,
    idempotency_key: IdempotencyHeader,
    authenticated: CsrfAuthenticated,
    services: Services,
) -> SyncJobResponse:
    digest = hashlib.sha256(idempotency_key.encode()).hexdigest()
    job = Job(
        id=EntityId.new(),
        user_id=authenticated.user.id,
        job_type="activity.fetch_file",
        payload={"activity_id": str(activity_id)},
        idempotency_key=f"activity:manual-process:{activity_id}:{digest}",
        max_attempts=5,
    )
    async with services.uow_factory() as uow:
        if await uow.activities.get(authenticated.user.id, EntityId(activity_id)) is None:
            raise ResourceNotFoundError("activity")
        job = await uow.jobs.add_idempotent(job)
        await uow.commit()
    return SyncJobResponse(id=job.id.value, status=job.status)


@router.put("/{activity_id}/feedback", response_model=FeedbackResponse)
async def put_feedback(
    activity_id: UUID,
    payload: FeedbackRequest,
    idempotency_key: IdempotencyHeader,
    authenticated: CsrfAuthenticated,
    services: Services,
    correlation_id: RequestCorrelationId,
) -> FeedbackResponse:
    request_hash = hashlib.sha256(
        json.dumps(payload.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    feedback = await services.activity_data.record_feedback(
        authenticated.user.id,
        EntityId(activity_id),
        rpe=payload.rpe,
        technique_rating=payload.technique_rating,
        fatigue_rating=payload.fatigue_rating,
        enjoyment_rating=payload.enjoyment_rating,
        feeling_score=None,
        pain_present=payload.pain_present,
        pain_location=payload.pain_location,
        pain_intensity=payload.pain_intensity,
        comment=payload.comment,
        expected_version=payload.version,
        actor_id=str(authenticated.user.id),
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        preserve_existing_feeling_score=True,
    )
    if feedback is None:
        raise RuntimeError("legacy feedback writes cannot clear feedback")
    return FeedbackResponse.from_domain(feedback)


@router.put("/{activity_id}/match", response_model=MatchResponse)
async def put_match(
    activity_id: UUID,
    payload: ManualMatchRequest,
    authenticated: CsrfAuthenticated,
    services: Services,
    correlation_id: RequestCorrelationId,
) -> MatchResponse:
    match = await services.activity_data.match_manually(
        authenticated.user.id,
        EntityId(activity_id),
        EntityId(payload.planned_workout_id),
        actor_id=str(authenticated.user.id),
        correlation_id=correlation_id,
    )
    return MatchResponse.from_domain(match)
