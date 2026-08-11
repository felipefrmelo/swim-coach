"""Initial user-scoped context API."""

from __future__ import annotations

import hashlib
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, status
from pydantic import BaseModel

from swim_coach.application.services.context import AvailabilityInput
from swim_coach.domain.shared.value_objects import EntityId, IdempotencyKey
from swim_coach.interfaces.rest.dependencies import (
    Authenticated,
    CsrfAuthenticated,
    RequestCorrelationId,
    Services,
)
from swim_coach.interfaces.rest.schemas import (
    AvailabilityReplaceRequest,
    AvailabilityRuleResponse,
    GoalCreateRequest,
    GoalResponse,
    GoalUpdateRequest,
    MeResponse,
    PoolCreateRequest,
    PoolResponse,
    PoolUpdateRequest,
    ProfileUpdateRequest,
)

router = APIRouter(prefix="/api/v1", tags=["context"])

IdempotencyHeader = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=200)]


def _request_hash(payload: BaseModel) -> str:
    serialized = payload.model_dump_json()
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


@router.get("/me", response_model=MeResponse)
async def get_me(authenticated: Authenticated, services: Services) -> MeResponse:
    context = await services.context.get_me(authenticated.user.id)
    return MeResponse.from_domain(context.user, context.profile)


@router.patch("/me/profile", response_model=MeResponse)
async def update_profile(
    payload: ProfileUpdateRequest,
    authenticated: CsrfAuthenticated,
    services: Services,
    correlation_id: RequestCorrelationId,
) -> MeResponse:
    context = await services.context.update_profile(
        authenticated.user.id,
        display_name=payload.display_name,
        locale=payload.locale,
        timezone=payload.timezone,
        experience_level=payload.experience_level,
        default_sessions_per_week=payload.default_sessions_per_week,
        expected_version=payload.version,
        correlation_id=correlation_id,
    )
    return MeResponse.from_domain(context.user, context.profile)


@router.get("/pools", response_model=list[PoolResponse])
async def list_pools(authenticated: Authenticated, services: Services) -> list[PoolResponse]:
    pools = await services.context.list_pools(authenticated.user.id)
    return [PoolResponse.from_domain(pool) for pool in pools]


@router.post("/pools", response_model=PoolResponse, status_code=status.HTTP_201_CREATED)
async def create_pool(
    payload: PoolCreateRequest,
    idempotency_key: IdempotencyHeader,
    authenticated: CsrfAuthenticated,
    services: Services,
    correlation_id: RequestCorrelationId,
) -> PoolResponse:
    pool = await services.context.create_pool(
        authenticated.user.id,
        name=payload.name,
        length_m=payload.length_m,
        is_default=payload.is_default,
        location_label=payload.location_label,
        correlation_id=correlation_id,
        idempotency_key=IdempotencyKey(idempotency_key),
        request_hash=_request_hash(payload),
    )
    return PoolResponse.from_domain(pool)


@router.patch("/pools/{pool_id}", response_model=PoolResponse)
async def update_pool(
    pool_id: UUID,
    payload: PoolUpdateRequest,
    authenticated: CsrfAuthenticated,
    services: Services,
    correlation_id: RequestCorrelationId,
) -> PoolResponse:
    pool = await services.context.update_pool(
        authenticated.user.id,
        EntityId(pool_id),
        name=payload.name,
        length_m=payload.length_m,
        is_default=payload.is_default,
        active=payload.active,
        location_label=payload.location_label,
        expected_version=payload.version,
        correlation_id=correlation_id,
    )
    return PoolResponse.from_domain(pool)


@router.get("/availability", response_model=list[AvailabilityRuleResponse])
async def list_availability(
    authenticated: Authenticated, services: Services
) -> list[AvailabilityRuleResponse]:
    rules = await services.context.list_availability(authenticated.user.id)
    return [AvailabilityRuleResponse.from_domain(rule) for rule in rules]


@router.put("/availability", response_model=list[AvailabilityRuleResponse])
async def replace_availability(
    payload: AvailabilityReplaceRequest,
    authenticated: CsrfAuthenticated,
    services: Services,
    correlation_id: RequestCorrelationId,
) -> list[AvailabilityRuleResponse]:
    rules = await services.context.replace_availability(
        authenticated.user.id,
        [
            AvailabilityInput(
                day_of_week=item.day_of_week,
                start_local_time=item.start_local_time,
                end_local_time=item.end_local_time,
                max_duration_minutes=item.max_duration_minutes,
                pool_id=EntityId(item.pool_id) if item.pool_id else None,
                valid_from=item.valid_from,
                valid_until=item.valid_until,
                priority=item.priority,
            )
            for item in payload.rules
        ],
        correlation_id=correlation_id,
    )
    return [AvailabilityRuleResponse.from_domain(rule) for rule in rules]


@router.get("/goals", response_model=list[GoalResponse])
async def list_goals(authenticated: Authenticated, services: Services) -> list[GoalResponse]:
    goals = await services.context.list_goals(authenticated.user.id)
    return [GoalResponse.from_domain(goal) for goal in goals]


@router.post("/goals", response_model=GoalResponse, status_code=status.HTTP_201_CREATED)
async def create_goal(
    payload: GoalCreateRequest,
    idempotency_key: IdempotencyHeader,
    authenticated: CsrfAuthenticated,
    services: Services,
    correlation_id: RequestCorrelationId,
) -> GoalResponse:
    goal = await services.context.create_goal(
        authenticated.user.id,
        title=payload.title,
        target_distance_m=payload.target_distance_m,
        target_duration_seconds=payload.target_duration_seconds,
        target_date=payload.target_date,
        priority=payload.priority,
        correlation_id=correlation_id,
        idempotency_key=IdempotencyKey(idempotency_key),
        request_hash=_request_hash(payload),
    )
    return GoalResponse.from_domain(goal)


@router.patch("/goals/{goal_id}", response_model=GoalResponse)
async def update_goal(
    goal_id: UUID,
    payload: GoalUpdateRequest,
    authenticated: CsrfAuthenticated,
    services: Services,
    correlation_id: RequestCorrelationId,
) -> GoalResponse:
    goal = await services.context.update_goal(
        authenticated.user.id,
        EntityId(goal_id),
        title=payload.title,
        target_distance_m=payload.target_distance_m,
        target_duration_seconds=payload.target_duration_seconds,
        target_date=payload.target_date,
        priority=payload.priority,
        status=payload.status,
        expected_version=payload.version,
        correlation_id=correlation_id,
    )
    return GoalResponse.from_domain(goal)
