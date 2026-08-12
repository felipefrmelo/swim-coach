"""P07 preview and explicit approval endpoints for external actions."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Header, Response, status
from pydantic import BaseModel, ConfigDict, Field

from swim_coach.application.services.garmin_publish import GarminActionDetail
from swim_coach.domain.actions import ActionProposalStatus
from swim_coach.domain.shared.errors import DomainError
from swim_coach.domain.shared.types import JsonObject
from swim_coach.domain.shared.value_objects import EntityId
from swim_coach.interfaces.rest.dependencies import (
    Authenticated,
    CsrfAuthenticated,
    RequestCorrelationId,
    Services,
)

router = APIRouter(prefix="/api/v1", tags=["actions"])
IfMatch = Annotated[str, Header(alias="If-Match")]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GarminPreviewRequest(StrictModel):
    device_id: UUID | None = None


class ActionDecisionRequest(StrictModel):
    action_hash: str = Field(min_length=64, max_length=64)


class ActionExecutionResponse(StrictModel):
    id: UUID
    status: str
    result: JsonObject | None
    error: JsonObject | None


class ActionProposalResponse(StrictModel):
    id: UUID
    action_type: str
    status: str
    version: int
    action_hash: str
    expires_at: datetime
    target_id: UUID
    target_revision_id: UUID
    compiled_hash: str
    scheduled_date: str
    device_id: UUID
    impact: JsonObject
    write_enabled: bool
    execution: ActionExecutionResponse | None

    @classmethod
    def from_detail(
        cls, detail: GarminActionDetail, *, write_enabled: bool
    ) -> ActionProposalResponse:
        proposal = detail.proposal
        payload = proposal.payload
        execution = detail.execution
        try:
            compiled_hash = cast(str, payload["compiled_hash"])
            scheduled_date = cast(str, payload["scheduled_date"])
            device_id = UUID(cast(str, payload["device_id"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise DomainError("INTERNAL_ERROR", "Action proposal payload is invalid.") from exc
        if proposal.target_revision_id is None:
            raise DomainError("INTERNAL_ERROR", "Garmin proposal revision is missing.")
        return cls(
            id=proposal.id.value,
            action_type=proposal.action_type,
            status=proposal.status.value,
            version=proposal.version,
            action_hash=proposal.action_hash,
            expires_at=proposal.expires_at,
            target_id=proposal.target_id.value,
            target_revision_id=proposal.target_revision_id.value,
            compiled_hash=compiled_hash,
            scheduled_date=scheduled_date,
            device_id=device_id,
            impact=proposal.impact,
            write_enabled=write_enabled,
            execution=(
                ActionExecutionResponse(
                    id=execution.id.value,
                    status=execution.status.value,
                    result=execution.result,
                    error=execution.error,
                )
                if execution
                else None
            ),
        )


def _version(if_match: str) -> int:
    value = if_match.strip().removeprefix("W/").strip('"')
    try:
        version = int(value)
    except ValueError as exc:
        raise DomainError("VALIDATION_FAILED", "If-Match must contain a version.") from exc
    if version < 1:
        raise DomainError("VALIDATION_FAILED", "If-Match must contain a positive version.")
    return version


def _response(
    detail: GarminActionDetail, services: Services, response: Response
) -> ActionProposalResponse:
    response.headers["ETag"] = f'"{detail.proposal.version}"'
    return ActionProposalResponse.from_detail(
        detail, write_enabled=services.garmin_publish.write_enabled
    )


@router.post(
    "/workouts/{workout_id}/garmin-proposals",
    response_model=ActionProposalResponse,
    status_code=status.HTTP_201_CREATED,
)
async def preview_garmin_publish(
    workout_id: UUID,
    payload: GarminPreviewRequest,
    if_match: IfMatch,
    authenticated: CsrfAuthenticated,
    services: Services,
    correlation_id: RequestCorrelationId,
    response: Response,
) -> ActionProposalResponse:
    detail = await services.garmin_publish.preview(
        authenticated.user.id,
        EntityId(workout_id),
        expected_workout_version=_version(if_match),
        device_id=EntityId(payload.device_id) if payload.device_id else None,
        correlation_id=correlation_id,
    )
    return _response(detail, services, response)


@router.get("/actions/{proposal_id}", response_model=ActionProposalResponse)
async def get_action(
    proposal_id: UUID,
    authenticated: Authenticated,
    services: Services,
    response: Response,
) -> ActionProposalResponse:
    detail = await services.garmin_publish.get(authenticated.user.id, EntityId(proposal_id))
    return _response(detail, services, response)


@router.post("/actions/{proposal_id}/approve", response_model=ActionProposalResponse)
async def approve_action(
    proposal_id: UUID,
    payload: ActionDecisionRequest,
    if_match: IfMatch,
    authenticated: CsrfAuthenticated,
    services: Services,
    correlation_id: RequestCorrelationId,
    response: Response,
) -> ActionProposalResponse:
    detail = await services.garmin_publish.get(authenticated.user.id, EntityId(proposal_id))
    if detail.proposal.status is ActionProposalStatus.READY_FOR_REVIEW:
        detail = await services.garmin_publish.approve(
            authenticated.user.id,
            EntityId(proposal_id),
            expected_version=_version(if_match),
            action_hash=payload.action_hash,
            correlation_id=correlation_id,
        )
    elif detail.proposal.action_hash != payload.action_hash:
        raise DomainError("ACTION_TAMPERED", "The reviewed action no longer matches.")
    elif detail.proposal.status not in {
        ActionProposalStatus.APPROVED,
        ActionProposalStatus.QUEUED,
        ActionProposalStatus.EXECUTING,
        ActionProposalStatus.SUCCEEDED,
    }:
        raise DomainError(
            "ACTION_STATE_CONFLICT",
            "The action cannot be approved or executed from its current state.",
        )
    detail = await services.garmin_publish.execute(
        authenticated.user.id,
        EntityId(proposal_id),
        idempotency_key=f"pwa-approval:{proposal_id}:{payload.action_hash}",
        correlation_id=correlation_id,
    )
    return _response(detail, services, response)


@router.post("/actions/{proposal_id}/reject", response_model=ActionProposalResponse)
async def reject_action(
    proposal_id: UUID,
    payload: ActionDecisionRequest,
    if_match: IfMatch,
    authenticated: CsrfAuthenticated,
    services: Services,
    correlation_id: RequestCorrelationId,
    response: Response,
) -> ActionProposalResponse:
    detail = await services.garmin_publish.reject(
        authenticated.user.id,
        EntityId(proposal_id),
        expected_version=_version(if_match),
        action_hash=payload.action_hash,
        correlation_id=correlation_id,
    )
    return _response(detail, services, response)
