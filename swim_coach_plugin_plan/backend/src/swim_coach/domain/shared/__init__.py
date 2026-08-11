"""Shared domain primitives."""

from swim_coach.domain.shared.errors import DomainError, DomainValidationError
from swim_coach.domain.shared.value_objects import (
    CorrelationId,
    DateRange,
    Distance,
    Duration,
    EntityId,
    ExternalId,
    IdempotencyKey,
    InstantRange,
    Pace,
    PaceRange,
    PoolLength,
    Rpe,
    TimeWindow,
    UserId,
)

__all__ = [
    "CorrelationId",
    "DateRange",
    "Distance",
    "DomainError",
    "DomainValidationError",
    "Duration",
    "EntityId",
    "ExternalId",
    "IdempotencyKey",
    "InstantRange",
    "Pace",
    "PaceRange",
    "PoolLength",
    "Rpe",
    "TimeWindow",
    "UserId",
]
