from dataclasses import FrozenInstanceError

import pytest
from pydantic import ValidationError

from swim_coach.domain.shared.value_objects import EntityId
from swim_coach.domain.workouts import (
    CanonicalWorkout,
    WorkoutRevision,
    canonical_content_hash,
    validate_workout,
)


def workout_payload(*, distance_m: int = 1_600) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "title": "Técnica e endurance — 1.600 m",
        "sport": "POOL_SWIMMING",
        "pool_length_m": 20,
        "purpose": "ENDURANCE",
        "nodes": [
            {
                "type": "step",
                "id": "warmup",
                "step_role": "WARMUP",
                "end_condition": {"type": "distance", "meters": 200},
                "intensity": "EASY",
            },
            {
                "type": "repeat",
                "id": "main",
                "repetitions": 6,
                "children": [
                    {
                        "type": "step",
                        "step_role": "WORK",
                        "end_condition": {"type": "distance", "meters": 200},
                        "target": {
                            "type": "pace_range",
                            "min_seconds_per_100m": 140,
                            "max_seconds_per_100m": 150,
                        },
                    },
                    {
                        "type": "step",
                        "step_role": "REST",
                        "end_condition": {"type": "time", "seconds": 20},
                    },
                ],
            },
            {
                "type": "step",
                "id": "cooldown",
                "step_role": "COOLDOWN",
                "end_condition": {"type": "distance", "meters": distance_m - 1_400},
                "intensity": "EASY",
            },
        ],
    }


def test_nested_totals_and_canonical_hash_are_deterministic() -> None:
    definition = CanonicalWorkout.model_validate(workout_payload())
    result = validate_workout(definition)
    assert result.valid
    assert result.totals.distance_m == 1_600
    assert result.totals.lengths == 80
    assert result.totals.executable_steps == 14
    assert result.totals.rest_seconds == 120
    assert canonical_content_hash(definition) == canonical_content_hash(
        CanonicalWorkout.model_validate(definition.model_dump(mode="json"))
    )


def test_distance_not_ending_at_wall_is_rejected() -> None:
    definition = CanonicalWorkout.model_validate(workout_payload(distance_m=1_610))
    result = validate_workout(definition)
    assert not result.valid
    assert result.errors[0].code == "POOL_DISTANCE_MISMATCH"


def test_ranges_size_and_depth_are_bounded() -> None:
    payload = workout_payload()
    nodes = payload["nodes"]
    assert isinstance(nodes, list)
    work = nodes[1]
    assert isinstance(work, dict)
    children = work["children"]
    assert isinstance(children, list)
    child = children[0]
    assert isinstance(child, dict)
    child["target"] = {"type": "rpe", "min": 9, "max": 5}
    with pytest.raises(ValidationError):
        CanonicalWorkout.model_validate(payload)


def test_revision_snapshot_is_immutable() -> None:
    definition = CanonicalWorkout.model_validate(workout_payload())
    validation = validate_workout(definition)
    revision = WorkoutRevision(
        id=EntityId.new(),
        workout_id=EntityId.new(),
        revision_number=1,
        definition=definition,
        totals=validation.totals,
        validation=validation.model_dump(mode="json"),
        content_hash=canonical_content_hash(definition),
    )
    with pytest.raises(FrozenInstanceError):
        revision.revision_number = 2  # type: ignore[misc]


def test_intense_workout_warns_without_warmup_or_cooldown() -> None:
    definition = CanonicalWorkout.model_validate(
        {
            "schema_version": "1.0",
            "title": "Tiros",
            "sport": "POOL_SWIMMING",
            "pool_length_m": 20,
            "purpose": "SPEED",
            "nodes": [{"type": "step", "end_condition": {"type": "distance", "meters": 40}}],
        }
    )
    assert {issue.code for issue in validate_workout(definition).warnings} == {
        "WARMUP_RECOMMENDED",
        "COOLDOWN_RECOMMENDED",
    }
