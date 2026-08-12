"""Training goals and milestones."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from swim_coach.domain.identity.entities import utc_now
from swim_coach.domain.shared.errors import DomainValidationError
from swim_coach.domain.shared.types import JsonObject
from swim_coach.domain.shared.value_objects import Distance, Duration, EntityId, Pace, UserId


class GoalStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


@dataclass(slots=True)
class TrainingGoal:
    id: EntityId
    user_id: UserId
    goal_type: str
    title: str
    status: GoalStatus
    priority: int
    target_distance: Distance
    target_duration: Duration
    target_date: date | None = None
    target_pace: Pace = field(init=False)
    baseline: JsonObject = field(default_factory=dict)
    metadata: JsonObject = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    completed_at: datetime | None = None
    version: int = 1

    def __post_init__(self) -> None:
        self.title = self.title.strip()
        if not self.goal_type.strip() or not self.title:
            raise DomainValidationError("goal type and title are required")
        if self.priority < 0:
            raise DomainValidationError("goal priority cannot be negative")
        self.target_pace = Pace.from_distance_and_duration(
            self.target_distance, self.target_duration
        )

    @classmethod
    def initial_two_k(cls, user_id: UserId) -> TrainingGoal:
        return cls(
            id=EntityId.new(),
            user_id=user_id,
            goal_type="distance_time",
            title="Nadar 2.000 m em 45 min",
            status=GoalStatus.ACTIVE,
            priority=1,
            target_distance=Distance(2_000),
            target_duration=Duration(Decimal(2_700)),
        )


@dataclass(slots=True)
class GoalMilestone:
    id: EntityId
    goal_id: EntityId
    name: str
    target_date: date | None
    target: JsonObject
    status: str = "pending"
    result: JsonObject | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    version: int = 1

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise DomainValidationError("milestone name is required")
