from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from swim_coach.domain.activities import (
    coefficient_of_variation,
    completion_ratio,
    fade_percent,
    pace_seconds_per_100m,
    srpe_load,
)


def test_normative_activity_formulas() -> None:
    assert pace_seconds_per_100m(Decimal(2700), 2000) == Decimal("135.000")
    assert completion_ratio(2100, 2000) == Decimal("1.050")
    assert srpe_load(Decimal(2700), 6) == Decimal("270.00")
    assert coefficient_of_variation((Decimal(100), Decimal(110))) == Decimal("0.0476")
    assert fade_percent(
        (Decimal(100), Decimal(100), Decimal(102), Decimal(104), Decimal(110), Decimal(110))
    ) == Decimal("10.00")


@given(
    duration=st.decimals(min_value=0, max_value=100_000, allow_nan=False),
    distance=st.integers(min_value=0, max_value=100_000),
)
def test_pace_never_divides_by_zero(duration: Decimal, distance: int) -> None:
    result = pace_seconds_per_100m(duration, distance)
    assert result is None if distance == 0 else result is not None and result >= 0


def test_invalid_metric_inputs_fail_closed() -> None:
    with pytest.raises(ValueError):
        pace_seconds_per_100m(Decimal(-1), 20)
    with pytest.raises(ValueError):
        srpe_load(Decimal(60), 11)
