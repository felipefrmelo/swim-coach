"""Workout aggregate, immutable revisions, templates and local schedule."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from enum import StrEnum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from swim_coach.domain.identity.entities import utc_now
from swim_coach.domain.shared.errors import DomainValidationError
from swim_coach.domain.shared.value_objects import EntityId, UserId
from swim_coach.domain.workouts.schema import CanonicalWorkout, WorkoutTotals


class PlannedWorkoutStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    SCHEDULED = "scheduled"
    CANCELLED = "cancelled"
    ARCHIVED = "archived"


@dataclass(frozen=True, slots=True)
class WorkoutRevision:
    id: EntityId
    workout_id: EntityId
    revision_number: int
    definition: CanonicalWorkout
    totals: WorkoutTotals
    validation: dict[str, object]
    content_hash: str
    change_reason: str | None = None
    created_by_type: str = "user"
    created_by_id: str | None = None
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if self.revision_number < 1 or len(self.content_hash) != 64:
            raise DomainValidationError("workout revision identity is invalid")


@dataclass(frozen=True, slots=True)
class WorkoutSchedule:
    id: EntityId
    workout_id: EntityId
    scheduled_date: date
    scheduled_start_time: time | None
    timezone: str
    pool_id: EntityId
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as error:
            raise DomainValidationError(
                "schedule timezone must be a valid IANA timezone"
            ) from error


@dataclass(slots=True)
class PlannedWorkout:
    id: EntityId
    user_id: UserId
    title: str
    purpose: str
    pool_id: EntityId
    status: PlannedWorkoutStatus = PlannedWorkoutStatus.DRAFT
    current_revision_id: EntityId | None = None
    approved_revision_id: EntityId | None = None
    schedule: WorkoutSchedule | None = None
    source: str = "manual"
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    version: int = 1

    def __post_init__(self) -> None:
        self.title = self.title.strip()
        if not self.title or not self.purpose.strip() or self.version < 1:
            raise DomainValidationError("workout title, purpose and version are required")


@dataclass(frozen=True, slots=True)
class WorkoutTemplate:
    id: EntityId
    owner_user_id: UserId | None
    name: str
    objective: str
    tags: tuple[str, ...]
    definition: CanonicalWorkout
    schema_version: str = "1.0"
    is_system: bool = False
    active: bool = True
    created_at: datetime = field(default_factory=utc_now)
