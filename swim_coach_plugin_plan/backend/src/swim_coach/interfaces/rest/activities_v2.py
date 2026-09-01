"""Semantic v2 read API for pool activities."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from swim_coach.application.services.activity_views import (
    activity_detail_v2,
    activity_summary_v2,
)
from swim_coach.domain.activities import SessionFeedback
from swim_coach.domain.shared.value_objects import EntityId
from swim_coach.interfaces.rest.activities import (
    IdempotencyHeader,
    ManualMatchRequest,
    MatchResponse,
    process_activity,
    put_match,
)
from swim_coach.interfaces.rest.dependencies import (
    Authenticated,
    CsrfAuthenticated,
    RequestCorrelationId,
    Services,
)
from swim_coach.interfaces.rest.schemas import SyncJobResponse

router = APIRouter(prefix="/api/v2/activities", tags=["activities-v2"])


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DurationFactsV2(StrictModel):
    elapsed_s: str | None
    timer_s: str | None
    moving_s: str | None
    swim_s: str | None
    rest_s: str | None
    stationary_s: str | None


class SpeedFactsV2(StrictModel):
    garmin_reported_m_per_s: str | None


class PaceFactsV2(StrictModel):
    pace_from_garmin_reported_speed_s_per_100m: str | None
    moving_s_per_100m: str | None
    swim_s_per_100m: str | None
    timer_s_per_100m: str | None
    session_s_per_100m: str | None


class PoolFactsV2(StrictModel):
    length_m: int | None
    active_length_count: int | None


class DataQualityV2(StrictModel):
    level: Literal["HIGH", "MEDIUM", "LOW"]
    reasons: list[str]


class GarminEvaluationV2(StrictModel):
    rpe: str | None
    feeling_score: int | None


class ManualEvaluationV2(StrictModel):
    rpe: int | None
    feeling_score: int | None


class EffectiveEvaluationV2(StrictModel):
    rpe: str | None
    feeling_score: int | None


class EvaluationProvenanceFactV2(StrictModel):
    source: Literal["GARMIN", "MANUAL_OVERRIDE"] | None
    raw_field: str | None = None
    transformation: str | None = None
    interpretation: str | None = None


class EvaluationProvenanceV2(StrictModel):
    rpe: EvaluationProvenanceFactV2
    feeling_score: EvaluationProvenanceFactV2


class SessionEvaluationV2(StrictModel):
    garmin: GarminEvaluationV2
    manual_override: ManualEvaluationV2
    effective: EffectiveEvaluationV2
    provenance: EvaluationProvenanceV2


class ActivitySummaryV2(StrictModel):
    activity_id: UUID
    name: str
    subtype: str
    started_at_utc: str
    started_at_local: str
    timezone: str
    distance_m: int
    durations: DurationFactsV2
    speeds: SpeedFactsV2
    paces: PaceFactsV2
    pool: PoolFactsV2
    provenance: dict[str, Any]
    data_quality: DataQualityV2
    session_evaluation: SessionEvaluationV2


class NormalizationV2(StrictModel):
    parser_version: str
    profile_version: str
    completeness: str
    warnings: list[str]


class IntervalPacesV2(StrictModel):
    pace_from_garmin_reported_speed_s_per_100m: str | None
    moving_s_per_100m: str | None
    swim_s_per_100m: str | None
    timer_s_per_100m: str | None
    elapsed_s_per_100m: str | None


class IntervalV2(StrictModel):
    index: int
    interval_type: Literal["SWIM", "REST", "DRILL", "UNKNOWN"]
    planned_role: Literal["WARMUP", "WORK", "RECOVERY", "REST", "COOLDOWN", "DRILL", "OTHER"] | None
    distance_m: int
    durations: DurationFactsV2
    speeds: SpeedFactsV2
    paces: IntervalPacesV2
    detected_stroke: str | None
    planned_stroke: str | None
    stroke_count: int | None
    stroke_rate: str | None
    swolf: str | None
    provenance: dict[str, Any]
    quality_warnings: list[str]


class LengthV2(StrictModel):
    index: int
    length_type: Literal["ACTIVE", "IDLE", "UNKNOWN"]
    distance_m: int
    durations: DurationFactsV2
    speeds: SpeedFactsV2
    paces: IntervalPacesV2
    detected_stroke: str | None
    planned_stroke: str | None
    stroke_count: int | None
    stroke_rate: str | None
    swolf: str | None
    provenance: dict[str, Any]
    quality_warnings: list[str]


class AnalysisV2(StrictModel):
    version: str
    quality: Literal["complete", "partial", "poor"]
    metrics: dict[str, Any]
    flags: list[str]
    summary: dict[str, Any]


class MatchV2(StrictModel):
    planned_workout_id: UUID
    confidence: str
    method: str


class FeedbackV2(StrictModel):
    id: UUID
    rpe: int | None
    technique_rating: int | None
    fatigue_rating: int | None
    enjoyment_rating: int | None
    feeling_score: int | None
    pain_present: bool
    pain_location: str | None
    pain_intensity: int | None
    comment: str | None
    version: int
    updated_at: str

    @classmethod
    def from_domain(cls, feedback: SessionFeedback) -> FeedbackV2:
        return cls(
            id=feedback.id.value,
            rpe=feedback.rpe,
            technique_rating=feedback.technique_rating,
            fatigue_rating=feedback.fatigue_rating,
            enjoyment_rating=feedback.enjoyment_rating,
            feeling_score=feedback.feeling_score,
            pain_present=feedback.pain_present,
            pain_location=feedback.pain_location,
            pain_intensity=feedback.pain_intensity,
            comment=feedback.comment,
            version=feedback.version,
            updated_at=feedback.updated_at.isoformat(),
        )


class FeedbackRequestV2(StrictModel):
    rpe: int | None = Field(default=None, ge=1, le=10)
    technique_rating: int | None = Field(default=None, ge=1, le=5)
    fatigue_rating: int | None = Field(default=None, ge=1, le=5)
    enjoyment_rating: int | None = Field(default=None, ge=1, le=5)
    feeling_score: int | None = Field(default=None, ge=0, le=100)
    pain_present: bool = False
    pain_location: str | None = Field(default=None, max_length=120)
    pain_intensity: int | None = Field(default=None, ge=1, le=10)
    comment: str | None = Field(default=None, max_length=2_000)
    version: int | None = Field(default=None, ge=1)


class ActivityDetailV2(ActivitySummaryV2):
    schema_version: Literal["2.0"]
    normalization: NormalizationV2 | None
    intervals: list[IntervalV2]
    lengths: list[LengthV2]
    analysis: AnalysisV2 | None
    match: MatchV2 | None
    feedback: FeedbackV2 | None
    raw_fit_exposed: Literal[False]


@router.get("", response_model=list[ActivitySummaryV2])
async def list_activities_v2(
    authenticated: Authenticated, services: Services
) -> list[ActivitySummaryV2]:
    async with services.uow_factory() as uow:
        activities = await uow.activities.list_recent(authenticated.user.id, limit=100)
        normalization_facts = await uow.activity_data.list_current_normalization_facts(
            authenticated.user.id, [item.id for item in activities]
        )
        feedbacks = await uow.activity_data.list_feedbacks(
            authenticated.user.id, [item.id for item in activities]
        )
        normalized = {item.activity_id: item for item in normalization_facts}
        feedback_by_activity = {item.activity_id: item for item in feedbacks}
    return [
        ActivitySummaryV2.model_validate(
            activity_summary_v2(
                item,
                normalized.get(item.id),
                timezone_name=authenticated.user.timezone,
                feedback=feedback_by_activity.get(item.id),
            )
        )
        for item in activities
    ]


@router.get("/{activity_id}", response_model=ActivityDetailV2)
async def get_activity_v2(
    activity_id: UUID, authenticated: Authenticated, services: Services
) -> ActivityDetailV2:
    detail = await services.activity_data.get(authenticated.user.id, EntityId(activity_id))
    return ActivityDetailV2.model_validate(
        activity_detail_v2(detail, timezone_name=authenticated.user.timezone)
    )


@router.post("/{activity_id}/process", response_model=SyncJobResponse, status_code=202)
async def process_activity_v2(
    activity_id: UUID,
    idempotency_key: IdempotencyHeader,
    authenticated: CsrfAuthenticated,
    services: Services,
) -> SyncJobResponse:
    """Versioned alias for the existing idempotent local processing command."""

    return await process_activity(activity_id, idempotency_key, authenticated, services)


@router.put("/{activity_id}/feedback", response_model=FeedbackV2 | None)
async def put_feedback_v2(
    activity_id: UUID,
    payload: FeedbackRequestV2,
    idempotency_key: IdempotencyHeader,
    authenticated: CsrfAuthenticated,
    services: Services,
    correlation_id: RequestCorrelationId,
) -> FeedbackV2 | None:
    """Store field-level overrides; Garmin RPE may satisfy the effective RPE."""

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
        feeling_score=payload.feeling_score,
        pain_present=payload.pain_present,
        pain_location=payload.pain_location,
        pain_intensity=payload.pain_intensity,
        comment=payload.comment,
        expected_version=payload.version,
        actor_id=str(authenticated.user.id),
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        preserve_existing_feeling_score=False,
    )
    return FeedbackV2.from_domain(feedback) if feedback is not None else None


@router.put("/{activity_id}/match", response_model=MatchResponse)
async def put_match_v2(
    activity_id: UUID,
    payload: ManualMatchRequest,
    authenticated: CsrfAuthenticated,
    services: Services,
    correlation_id: RequestCorrelationId,
) -> MatchResponse:
    """Versioned alias for a manual planned-workout match."""

    return await put_match(activity_id, payload, authenticated, services, correlation_id)
