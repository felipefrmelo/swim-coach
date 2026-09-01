from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from swim_coach.infrastructure.fit.parser import _session_evaluation


@given(
    encoded_rpe=st.integers(min_value=0, max_value=100),
    feeling_score=st.integers(min_value=0, max_value=100),
)
def test_documented_fit_session_evaluation_ranges_normalize_exactly(
    encoded_rpe: int,
    feeling_score: int,
) -> None:
    warnings: list[str] = []

    rpe, feeling = _session_evaluation(
        {"workout_rpe": encoded_rpe, "workout_feel": feeling_score},
        warnings,
    )

    assert rpe == (Decimal(encoded_rpe) / Decimal(10)).quantize(Decimal("0.1"))
    assert feeling == feeling_score
    assert warnings == []


@given(
    encoded_rpe=st.one_of(
        st.integers(max_value=-1),
        st.integers(min_value=101),
    ),
    feeling_score=st.one_of(
        st.integers(max_value=-1),
        st.integers(min_value=101),
    ),
)
def test_out_of_range_fit_session_evaluation_is_never_promoted(
    encoded_rpe: int,
    feeling_score: int,
) -> None:
    warnings: list[str] = []

    rpe, feeling = _session_evaluation(
        {"workout_rpe": encoded_rpe, "workout_feel": feeling_score},
        warnings,
    )

    assert rpe is None
    assert feeling is None
    assert warnings == ["SESSION_WORKOUT_RPE_INVALID", "SESSION_WORKOUT_FEEL_INVALID"]
