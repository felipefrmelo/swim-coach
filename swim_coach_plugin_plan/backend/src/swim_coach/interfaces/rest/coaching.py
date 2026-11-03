"""Auxiliary PWA views reuse the ChatGPT-first application operations."""

from datetime import datetime, time
from typing import Any
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from swim_coach.domain.shared.value_objects import EntityId
from swim_coach.domain.workouts.calendar import CalendarRequest
from swim_coach.interfaces.rest.dependencies import (
    Authenticated,
    CsrfAuthenticated,
    RequestCorrelationId,
    Services,
)

router = APIRouter(prefix="/api/v1/coaching", tags=["coaching"])


class CalendarPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requests: list[CalendarRequest] = Field(min_length=1, max_length=14)
    reference: datetime | None = None
    timezone: str | None = None
    start: time | None = None
    workout_id: UUID | None = None


class RescheduleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request: CalendarRequest
    start: time | None = None
    expected_version: int = Field(ge=1)
    expected_calendar_hash: str = Field(min_length=64, max_length=64)


@router.get("/overview")
async def overview(authenticated: Authenticated, services: Services) -> dict[str, Any]:
    return await services.coach_commands.operations.overview(authenticated.user.id)


@router.post("/calendar/preview")
async def preview(
    payload: CalendarPreviewRequest, authenticated: Authenticated, services: Services
) -> dict[str, Any]:
    return await services.coach_commands.operations.preview(
        authenticated.user.id,
        requests=payload.requests,
        reference=payload.reference,
        timezone=payload.timezone,
        start=payload.start,
        workout_id=EntityId(payload.workout_id) if payload.workout_id else None,
    )


@router.post("/workouts/{workout_id}/reschedule")
async def reschedule(
    workout_id: UUID,
    payload: RescheduleRequest,
    authenticated: CsrfAuthenticated,
    services: Services,
    correlation_id: RequestCorrelationId,
) -> dict[str, Any]:
    return await services.coach_commands.operations.reschedule(
        authenticated.user.id,
        EntityId(workout_id),
        request=payload.request,
        start=payload.start,
        expected_version=payload.expected_version,
        expected_calendar_hash=payload.expected_calendar_hash,
        correlation_id=correlation_id,
    )


@router.post("/publication-status")
async def publication_status(
    workout_ids: list[UUID], authenticated: Authenticated, services: Services
) -> dict[str, Any]:
    if not 1 <= len(workout_ids) <= 20:
        from swim_coach.domain.shared.errors import DomainValidationError

        raise DomainValidationError("Provide 1 to 20 workout IDs.")
    return await services.coach_commands.operations.publication_status(
        authenticated.user.id, [EntityId(w) for w in workout_ids]
    )
