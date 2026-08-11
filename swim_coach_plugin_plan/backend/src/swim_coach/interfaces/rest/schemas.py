"""Typed REST DTOs for initial athlete context."""

from __future__ import annotations

from datetime import date, time
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from swim_coach.domain.athlete import AthleteProfile, AvailabilityRule, Pool
from swim_coach.domain.goals import GoalStatus, TrainingGoal
from swim_coach.domain.identity import AppUser


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AuthConfigResponse(StrictModel):
    oidc_enabled: bool
    dev_auth_enabled: bool


class UserResponse(StrictModel):
    id: UUID
    email: str
    display_name: str
    locale: str
    timezone: str
    version: int


class ProfileResponse(StrictModel):
    experience_level: str
    default_sessions_per_week: int
    preferred_distance_unit: Literal["m"] = "m"
    default_pool_id: UUID | None
    version: int


class MeResponse(StrictModel):
    user: UserResponse
    profile: ProfileResponse

    @classmethod
    def from_domain(cls, user: AppUser, profile: AthleteProfile) -> MeResponse:
        return cls(
            user=UserResponse(
                id=user.id.value,
                email=user.email,
                display_name=user.display_name,
                locale=user.locale,
                timezone=user.timezone,
                version=user.version,
            ),
            profile=ProfileResponse(
                experience_level=profile.experience_level,
                default_sessions_per_week=profile.default_sessions_per_week,
                default_pool_id=profile.default_pool_id.value if profile.default_pool_id else None,
                version=profile.version,
            ),
        )


class ProfileUpdateRequest(StrictModel):
    display_name: str = Field(min_length=1, max_length=120)
    locale: str = Field(min_length=2, max_length=35)
    timezone: str = Field(min_length=3, max_length=100)
    experience_level: str = Field(min_length=1, max_length=40)
    default_sessions_per_week: int = Field(ge=1, le=14)
    version: int = Field(ge=1)


class PoolResponse(StrictModel):
    id: UUID
    name: str
    length_m: int
    is_default: bool
    location_label: str | None
    active: bool
    version: int

    @classmethod
    def from_domain(cls, pool: Pool) -> PoolResponse:
        return cls(
            id=pool.id.value,
            name=pool.name,
            length_m=pool.length.meters,
            is_default=pool.is_default,
            location_label=pool.location_label,
            active=pool.active,
            version=pool.version,
        )


class PoolCreateRequest(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    length_m: int = Field(gt=0, le=100)
    is_default: bool = False
    location_label: str | None = Field(default=None, max_length=160)


class PoolUpdateRequest(PoolCreateRequest):
    active: bool = True
    version: int = Field(ge=1)


class AvailabilityRuleRequest(StrictModel):
    day_of_week: int = Field(ge=0, le=6)
    start_local_time: time
    end_local_time: time
    max_duration_minutes: int = Field(gt=0, le=1_440)
    pool_id: UUID | None = None
    valid_from: date | None = None
    valid_until: date | None = None
    priority: int = 0


class AvailabilityRuleResponse(AvailabilityRuleRequest):
    id: UUID
    version: int

    @classmethod
    def from_domain(cls, rule: AvailabilityRule) -> AvailabilityRuleResponse:
        return cls(
            id=rule.id.value,
            day_of_week=rule.day_of_week,
            start_local_time=rule.start_local_time,
            end_local_time=rule.end_local_time,
            max_duration_minutes=rule.max_duration_minutes,
            pool_id=rule.pool_id.value if rule.pool_id else None,
            valid_from=rule.valid_from,
            valid_until=rule.valid_until,
            priority=rule.priority,
            version=rule.version,
        )


class AvailabilityReplaceRequest(StrictModel):
    rules: list[AvailabilityRuleRequest] = Field(max_length=28)


class GoalResponse(StrictModel):
    id: UUID
    title: str
    status: GoalStatus
    priority: int
    target_distance_m: int
    target_duration_seconds: Decimal
    target_pace_seconds_per_100m: Decimal
    target_date: date | None
    version: int

    @classmethod
    def from_domain(cls, goal: TrainingGoal) -> GoalResponse:
        return cls(
            id=goal.id.value,
            title=goal.title,
            status=goal.status,
            priority=goal.priority,
            target_distance_m=goal.target_distance.meters,
            target_duration_seconds=goal.target_duration.seconds,
            target_pace_seconds_per_100m=goal.target_pace.seconds_per_100m,
            target_date=goal.target_date,
            version=goal.version,
        )


class GoalCreateRequest(StrictModel):
    title: str = Field(min_length=1, max_length=160)
    target_distance_m: int = Field(gt=0)
    target_duration_seconds: Decimal = Field(gt=0)
    target_date: date | None = None
    priority: int = Field(default=1, ge=0)


class GoalUpdateRequest(GoalCreateRequest):
    status: GoalStatus
    version: int = Field(ge=1)
