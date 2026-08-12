from datetime import UTC, date, datetime, time
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from swim_coach.domain.shared import (
    CorrelationId,
    DateRange,
    Distance,
    DomainValidationError,
    Duration,
    IdempotencyKey,
    InstantRange,
    Pace,
    PaceRange,
    PoolLength,
    Rpe,
    TimeWindow,
)


@given(
    meters=st.integers(min_value=1, max_value=100_000),
    seconds=st.integers(min_value=1, max_value=1_000_000),
)
def test_pace_round_trips_distance_and_duration(meters: int, seconds: int) -> None:
    pace = Pace.from_distance_and_duration(Distance(meters), Duration(Decimal(seconds)))

    reconstructed_seconds = pace.seconds_per_100m * Decimal(meters) / Decimal(100)
    assert abs(reconstructed_seconds - Decimal(seconds)) <= Decimal("1e-18")


@given(value=st.integers(max_value=0))
def test_pool_length_rejects_non_positive_values(value: int) -> None:
    with pytest.raises(DomainValidationError):
        PoolLength(value)


@given(value=st.integers().filter(lambda item: item < 1 or item > 10))
def test_rpe_rejects_values_outside_one_to_ten(value: int) -> None:
    with pytest.raises(DomainValidationError):
        Rpe(value)


def test_initial_units_and_ranges_are_explicit() -> None:
    pace = Pace.from_distance_and_duration(Distance(2_000), Duration(Decimal(2_700)))

    assert pace.seconds_per_100m == Decimal(135)
    assert DateRange(date(2026, 8, 11), date(2026, 8, 12)).start == date(2026, 8, 11)
    assert (
        InstantRange(
            datetime(2026, 8, 11, tzinfo=UTC), datetime(2026, 8, 12, tzinfo=UTC)
        ).start.tzinfo
        is UTC
    )
    assert TimeWindow(time(18), time(19)).end == time(19)
    assert PaceRange(Pace(Decimal(120)), Pace(Decimal(150))).maximum.seconds_per_100m == 150


def test_correlation_and_idempotency_validate_at_the_boundary() -> None:
    assert CorrelationId.parse(str(CorrelationId.new())).value
    assert str(IdempotencyKey("context-123")) == "context-123"
    with pytest.raises(DomainValidationError):
        CorrelationId.parse("not-a-uuid")
    with pytest.raises(DomainValidationError):
        IdempotencyKey("short")
