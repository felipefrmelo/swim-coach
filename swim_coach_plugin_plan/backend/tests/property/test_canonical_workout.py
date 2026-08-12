from hypothesis import given
from hypothesis import strategies as st

from swim_coach.domain.workouts import CanonicalWorkout, validate_workout


@given(
    pool_length=st.integers(min_value=10, max_value=100),
    lengths=st.integers(min_value=1, max_value=500),
    repetitions=st.integers(min_value=1, max_value=20),
)
def test_arbitrary_pool_multiples_and_repeat_totals(
    pool_length: int, lengths: int, repetitions: int
) -> None:
    distance = pool_length * lengths
    definition = CanonicalWorkout.model_validate(
        {
            "schema_version": "1.0",
            "title": "Property workout",
            "sport": "POOL_SWIMMING",
            "pool_length_m": pool_length,
            "purpose": "BASE",
            "nodes": [
                {
                    "type": "repeat",
                    "repetitions": repetitions,
                    "children": [
                        {"type": "step", "end_condition": {"type": "distance", "meters": distance}}
                    ],
                }
            ],
        }
    )
    result = validate_workout(definition)
    assert result.valid
    assert result.totals.distance_m == distance * repetitions
    assert result.totals.lengths == lengths * repetitions
