"""Auxiliary PWA views reuse the ChatGPT-first application operations."""

from datetime import datetime, time
from typing import Any
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from swim_coach.domain.planning import TrainingPlanDocument
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


class PlanEditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    definition: TrainingPlanDocument
    rationale: str = Field(min_length=1, max_length=2000)


class PlanApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    proposal_id: UUID
    approval_hash: str = Field(min_length=64, max_length=64)


@router.get("/plans/{plan_id}")
async def get_plan(
    plan_id: UUID, authenticated: Authenticated, services: Services
) -> dict[str, Any]:
    from datetime import timedelta
    from zoneinfo import ZoneInfo

    detail = await services.coach_commands.get_training_plan(
        authenticated.user.id, EntityId(plan_id)
    )
    document = detail.revision.document if detail.revision else None
    today = datetime.now(ZoneInfo(authenticated.user.timezone)).date()
    reviewed = max((r.week_number for r in detail.reviews if r.eligible), default=0)
    return {
        "plan_id": str(detail.plan.id),
        "title": detail.plan.title,
        "status": detail.plan.status.value,
        "lifecycle_state": detail.plan.lifecycle_state(today),
        "current_revision": detail.plan.current_revision,
        "goal_snapshot": detail.plan.goal_snapshot,
        "definition": document.as_json() if document else None,
        "protected_weeks": [
            w.week_number
            for w in document.weeks
            if detail.plan.start_date + timedelta(days=w.week_number * 7 - 1) < today
            or w.week_number <= reviewed
        ]
        if document
        else [],
        "local_date": today.isoformat(),
        "sessions": [
            {
                "session_intent_id": str(b.session_intent_id),
                "locked": b.locked,
                "state": b.state.value,
                "locked_reason": b.locked_reason,
            }
            for b in detail.bindings
        ],
        "history": [
            {
                "revision": r.revision_number,
                "reason": r.reason,
                "kind": r.revision_kind.value,
                "created_at": r.created_at.isoformat(),
            }
            for r in detail.revisions
        ],
    }


@router.post("/plans/{plan_id}/proposals")
async def propose_plan_edit(
    plan_id: UUID,
    payload: PlanEditRequest,
    authenticated: CsrfAuthenticated,
    services: Services,
    correlation_id: RequestCorrelationId,
) -> dict[str, Any]:
    from swim_coach.domain.planning import TrainingPlanRevisionDefinition

    revision = TrainingPlanRevisionDefinition.model_validate(
        {
            "kind": "MANUAL_EDIT",
            "rationale": payload.rationale,
            "definition": payload.definition.as_json(),
        }
    )
    result = await services.coach_commands.propose_plan_revision(
        authenticated.user.id,
        actor_id=str(authenticated.user.id),
        plan_id=EntityId(plan_id),
        expected_revision=payload.expected_revision,
        revision_definition=revision,
        correlation_id=correlation_id,
    )
    return {
        "proposal_id": str(result.proposal.id),
        "action_hash": result.proposal.action_hash,
        "expected_revision": payload.expected_revision,
        "expires_at": result.proposal.expires_at.isoformat(),
        "diff": result.proposal.impact.get("diff"),
    }


@router.post("/plans/{plan_id}/apply")
async def apply_plan_edit(
    plan_id: UUID,
    payload: PlanApplyRequest,
    authenticated: CsrfAuthenticated,
    services: Services,
    correlation_id: RequestCorrelationId,
) -> dict[str, Any]:
    result = await services.coach_commands.apply_plan_revision(
        authenticated.user.id,
        actor_id=str(authenticated.user.id),
        plan_id=EntityId(plan_id),
        proposal_id=EntityId(payload.proposal_id),
        expected_revision=payload.expected_revision,
        approval_hash=payload.approval_hash,
        correlation_id=correlation_id,
    )
    return {
        "current_revision": result.plan.current_revision,
        "materialization_pending": bool(result.materialization_job_ids),
        "garmin_changed": False,
    }
