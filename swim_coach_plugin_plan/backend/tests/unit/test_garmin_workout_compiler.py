"""Garmin compiler contract without importing the provider library."""

from datetime import UTC, datetime

import pytest

from swim_coach.application.ports.garmin import GarminWorkoutCapabilities
from swim_coach.application.services.garmin_workout_compiler import GarminWorkoutCompiler
from swim_coach.domain.shared.errors import DomainError
from swim_coach.domain.shared.value_objects import EntityId
from swim_coach.domain.workouts import (
    CanonicalWorkout,
    WorkoutRevision,
    canonical_content_hash,
    validate_workout,
)


def revision(definition: CanonicalWorkout) -> WorkoutRevision:
    validation = validate_workout(definition)
    return WorkoutRevision(
        id=EntityId.new(),
        workout_id=EntityId.new(),
        revision_number=1,
        definition=definition,
        totals=validation.totals,
        validation=validation.model_dump(mode="json"),
        content_hash=canonical_content_hash(definition),
        created_at=datetime(2026, 8, 11, 20, tzinfo=UTC),
    )


def canonical() -> CanonicalWorkout:
    return CanonicalWorkout.model_validate(
        {
            "title": "Endurance descartável — 400 m",
            "pool_length_m": 20,
            "purpose": "ENDURANCE",
            "nodes": [
                {
                    "type": "step",
                    "step_role": "WARMUP",
                    "end_condition": {"type": "distance", "meters": 80},
                    "stroke": {"type": "freestyle"},
                },
                {
                    "type": "repeat",
                    "repetitions": 4,
                    "children": [
                        {
                            "type": "step",
                            "step_role": "WORK",
                            "end_condition": {"type": "distance", "meters": 80},
                            "target": {"type": "rpe", "min": 5, "max": 6},
                            "stroke": {"type": "freestyle"},
                        }
                    ],
                },
            ],
        }
    )


def test_compiler_is_deterministic_and_emits_explicit_downgrade_warning() -> None:
    item = revision(canonical())
    first = GarminWorkoutCompiler().compile(item)
    second = GarminWorkoutCompiler().compile(item)
    assert first == second
    assert len(first.compiled_hash) == 64
    assert first.source_revision_hash in str(first.payload["description"])
    assert first.warnings == ("RPE_TARGET_DOWNGRADED_TO_NO_TARGET",)
    segments = first.payload["workoutSegments"]
    assert isinstance(segments, list)
    assert segments[0]["workoutSteps"][1]["type"] == "RepeatGroupDTO"


def test_identical_content_in_distinct_revisions_has_a_unique_external_marker() -> None:
    first = GarminWorkoutCompiler().compile(revision(canonical()))
    second = GarminWorkoutCompiler().compile(revision(canonical()))
    assert first.source_revision_hash != second.source_revision_hash
    assert first.compiled_hash != second.compiled_hash


def test_compiler_rejects_capability_depth_overflow() -> None:
    definition = canonical().model_dump(mode="json")
    original = definition["nodes"][1]
    definition["nodes"][1] = {
        "type": "repeat",
        "repetitions": 2,
        "children": [{"type": "repeat", "repetitions": 2, "children": [original]}],
    }
    item = revision(CanonicalWorkout.model_validate(definition))
    compiler = GarminWorkoutCompiler(GarminWorkoutCapabilities(max_repeat_depth=1))
    with pytest.raises(DomainError) as error:
        compiler.compile(item)
    assert error.value.code == "GARMIN_WORKOUT_UNSUPPORTED"
