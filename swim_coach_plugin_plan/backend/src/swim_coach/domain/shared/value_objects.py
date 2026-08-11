"""Unit-safe, immutable value objects used by the P01 domain."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from typing import Self
from uuid import UUID, uuid4

from swim_coach.domain.shared.errors import DomainValidationError


def _require_utc(value: datetime, field: str) -> None:
    offset = value.utcoffset()
    if value.tzinfo is None or offset is None:
        raise DomainValidationError(f"{field} must be timezone-aware UTC")
    if offset.total_seconds() != 0:
        raise DomainValidationError(f"{field} must use UTC")


@dataclass(frozen=True, slots=True)
class UserId:
    value: UUID

    @classmethod
    def new(cls) -> Self:
        return cls(uuid4())

    @classmethod
    def parse(cls, value: str | UUID) -> Self:
        return cls(value if isinstance(value, UUID) else UUID(value))

    def __str__(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class EntityId:
    value: UUID

    @classmethod
    def new(cls) -> Self:
        return cls(uuid4())

    @classmethod
    def parse(cls, value: str | UUID) -> Self:
        return cls(value if isinstance(value, UUID) else UUID(value))

    def __str__(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class ExternalId:
    provider: str
    value: str

    def __post_init__(self) -> None:
        if not self.provider.strip() or not self.value.strip():
            raise DomainValidationError("external id provider and value are required")


@dataclass(frozen=True, slots=True)
class CorrelationId:
    value: UUID

    @classmethod
    def new(cls) -> Self:
        return cls(uuid4())

    @classmethod
    def parse(cls, value: str | UUID) -> Self:
        try:
            return cls(value if isinstance(value, UUID) else UUID(value))
        except (TypeError, ValueError, AttributeError) as exc:
            raise DomainValidationError("correlation_id must be a UUID") from exc

    def __str__(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class IdempotencyKey:
    value: str

    def __post_init__(self) -> None:
        if self.value != self.value.strip() or not 8 <= len(self.value) <= 200:
            raise DomainValidationError("idempotency key must contain 8 to 200 characters")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class Distance:
    meters: int

    def __post_init__(self) -> None:
        if isinstance(self.meters, bool) or self.meters < 0:
            raise DomainValidationError("distance must be a non-negative whole number of meters")


@dataclass(frozen=True, slots=True)
class PoolLength:
    meters: int

    def __post_init__(self) -> None:
        if isinstance(self.meters, bool) or self.meters <= 0:
            raise DomainValidationError("pool length must be a positive whole number of meters")


@dataclass(frozen=True, slots=True)
class Duration:
    seconds: Decimal

    def __post_init__(self) -> None:
        if not self.seconds.is_finite() or self.seconds < 0:
            raise DomainValidationError("duration must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class Pace:
    seconds_per_100m: Decimal

    def __post_init__(self) -> None:
        if not self.seconds_per_100m.is_finite() or self.seconds_per_100m <= 0:
            raise DomainValidationError("pace must be finite and positive")

    @classmethod
    def from_distance_and_duration(cls, distance: Distance, duration: Duration) -> Self:
        if distance.meters <= 0 or duration.seconds <= 0:
            raise DomainValidationError("positive distance and duration are required for pace")
        return cls(duration.seconds * Decimal(100) / Decimal(distance.meters))


@dataclass(frozen=True, slots=True)
class PaceRange:
    minimum: Pace
    maximum: Pace

    def __post_init__(self) -> None:
        if self.minimum.seconds_per_100m > self.maximum.seconds_per_100m:
            raise DomainValidationError("pace range minimum cannot exceed maximum")


@dataclass(frozen=True, slots=True)
class Rpe:
    value: int

    def __post_init__(self) -> None:
        if isinstance(self.value, bool) or not 1 <= self.value <= 10:
            raise DomainValidationError("RPE must be between 1 and 10")


@dataclass(frozen=True, slots=True)
class DateRange:
    start: date
    end: date

    def __post_init__(self) -> None:
        if self.start > self.end:
            raise DomainValidationError("date range start cannot be after end")


@dataclass(frozen=True, slots=True)
class InstantRange:
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        _require_utc(self.start, "instant range start")
        _require_utc(self.end, "instant range end")
        if self.start >= self.end:
            raise DomainValidationError("instant range start must be before end")


@dataclass(frozen=True, slots=True)
class TimeWindow:
    start: time
    end: time

    def __post_init__(self) -> None:
        if self.start.tzinfo is not None or self.end.tzinfo is not None:
            raise DomainValidationError("availability times must be local wall-clock values")
        if self.start >= self.end:
            raise DomainValidationError("time window start must be before end")
