"""Athlete profile, pool, availability, constraint and device entities."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from enum import StrEnum

from swim_coach.domain.identity.entities import utc_now
from swim_coach.domain.shared.errors import DomainValidationError
from swim_coach.domain.shared.types import JsonObject
from swim_coach.domain.shared.value_objects import EntityId, PoolLength, UserId


class ConstraintType(StrEnum):
    INJURY = "injury"
    PAIN = "pain"
    SCHEDULE = "schedule"
    EQUIPMENT = "equipment"
    PREFERENCE = "preference"
    MEDICAL_ADVICE = "medical_advice"


@dataclass(slots=True)
class AthleteProfile:
    user_id: UserId
    experience_level: str = "recreational"
    preferred_distance_unit: str = "m"
    default_pool_id: EntityId | None = None
    default_sessions_per_week: int = 3
    goal_notes: str | None = None
    coach_preferences: JsonObject = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    version: int = 1

    def __post_init__(self) -> None:
        if not 1 <= self.default_sessions_per_week <= 14:
            raise DomainValidationError("sessions per week must be between 1 and 14")
        if self.preferred_distance_unit != "m":
            raise DomainValidationError("P01 supports meter distance units only")


@dataclass(slots=True)
class Pool:
    id: EntityId
    user_id: UserId
    name: str
    length: PoolLength
    is_default: bool = False
    location_label: str | None = None
    active: bool = True
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    version: int = 1

    def __post_init__(self) -> None:
        self.name = self.name.strip()
        if not self.name:
            raise DomainValidationError("pool name is required")


@dataclass(slots=True)
class AvailabilityRule:
    id: EntityId
    user_id: UserId
    day_of_week: int
    start_local_time: time
    end_local_time: time
    max_duration_minutes: int
    pool_id: EntityId | None = None
    valid_from: date | None = None
    valid_until: date | None = None
    priority: int = 0
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    version: int = 1

    def __post_init__(self) -> None:
        if not 0 <= self.day_of_week <= 6:
            raise DomainValidationError("day_of_week must be between 0 and 6")
        if self.start_local_time >= self.end_local_time:
            raise DomainValidationError("availability start must be before end")
        if self.max_duration_minutes <= 0:
            raise DomainValidationError("availability duration must be positive")
        if self.valid_from and self.valid_until and self.valid_from > self.valid_until:
            raise DomainValidationError("availability validity start cannot be after end")


@dataclass(slots=True)
class AthleteConstraint:
    id: EntityId
    user_id: UserId
    constraint_type: ConstraintType
    severity: int
    active_from: date
    active_until: date | None = None
    notes: str | None = None
    is_active: bool = True
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    version: int = 1

    def __post_init__(self) -> None:
        if not 1 <= self.severity <= 5:
            raise DomainValidationError("constraint severity must be between 1 and 5")
        if self.active_until and self.active_from > self.active_until:
            raise DomainValidationError("constraint start cannot be after end")


@dataclass(slots=True)
class Device:
    id: EntityId
    user_id: UserId
    provider: str
    external_device_id: str
    model: str
    name: str
    serial_hash: str | None = None
    is_primary: bool = False
    capabilities: JsonObject = field(default_factory=dict)
    last_seen_at: datetime | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    version: int = 1

    def __post_init__(self) -> None:
        if (
            not self.provider.strip()
            or not self.external_device_id.strip()
            or not self.model.strip()
        ):
            raise DomainValidationError("device provider, external id and model are required")
