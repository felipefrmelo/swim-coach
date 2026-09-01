"""Semantic v2 read API for pool activities."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from swim_coach.application.services.activity_views import (
    activity_detail_v2,
    activity_summary_v2,
)
from swim_coach.domain.shared.value_objects import EntityId
from swim_coach.interfaces.rest.activities import (
    FeedbackRequest,
    FeedbackResponse,
    IdempotencyHeader,
    ManualMatchRequest,
    MatchResponse,
    process_activity,
    put_feedback,
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
    rpe: int
    technique_rating: int | None
    fatigue_rating: int | None
    enjoyment_rating: int | None
    pain_present: bool
    pain_location: str | None
    pain_intensity: int | None
    comment: str | None
    version: int
    updated_at: str


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
        normalized = {item.activity_id: item for item in normalization_facts}
    return [
        ActivitySummaryV2.model_validate(
            activity_summary_v2(
                item,
                normalized.get(item.id),
                timezone_name=authenticated.user.timezone,
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


@router.put("/{activity_id}/feedback", response_model=FeedbackResponse)
async def put_feedback_v2(
    activity_id: UUID,
    payload: FeedbackRequest,
    idempotency_key: IdempotencyHeader,
    authenticated: CsrfAuthenticated,
    services: Services,
    correlation_id: RequestCorrelationId,
) -> FeedbackResponse:
    """Keep athlete feedback on the v2 activity resource without changing its shape."""

    return await put_feedback(
        activity_id,
        payload,
        idempotency_key,
        authenticated,
        services,
        correlation_id,
    )


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
