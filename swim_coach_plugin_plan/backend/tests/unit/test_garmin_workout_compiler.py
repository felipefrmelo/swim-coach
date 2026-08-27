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
                            "instructions": "Respiração bilateral",
                        }
                    ],
                },
            ],
        }
    )


def test_compiler_is_deterministic_and_emits_pool_notes_and_effort_target() -> None:
    item = revision(canonical())
    first = GarminWorkoutCompiler().compile(item)
    second = GarminWorkoutCompiler().compile(item)
    assert first == second
    assert len(first.compiled_hash) == 64
    assert first.source_revision_hash in str(first.payload["description"])
    assert first.payload["poolLength"] == 20.0
    assert first.payload["poolLengthUnit"] == {
        "unitId": 1,
        "unitKey": "meter",
        "factor": 100.0,
    }
    assert first.payload["estimatedDistanceInMeters"] == 400.0
    assert first.warnings == ("RPE_TARGET_MAPPED_TO_GARMIN_EFFORT_CATEGORY",)
    segments = first.payload["workoutSegments"]
    assert isinstance(segments, list)
    assert "poolLength" not in segments[0]
    warmup = segments[0]["workoutSteps"][0]
    assert "description" not in warmup
    assert "secondaryTargetType" not in warmup
    assert warmup["preferredEndConditionUnit"] == {
        "unitId": 1,
        "unitKey": "meter",
        "factor": 100.0,
    }
    repeat = segments[0]["workoutSteps"][1]
    assert repeat["type"] == "RepeatGroupDTO"
    work = repeat["workoutSteps"][0]
    assert work["description"] == "Respiração bilateral · RPE 5-6"
    assert work["targetType"]["workoutTargetTypeKey"] == "no.target"
    assert work["secondaryTargetType"] == {
        "workoutTargetTypeId": 18,
        "workoutTargetTypeKey": "swim.instruction",
        "displayOrder": 18,
    }
    assert work["secondaryTargetValueOne"] == 4.0
    assert work["secondaryTargetValueTwo"] == 0.0


def test_compiler_maps_desired_pace_range_to_ordered_metres_per_second() -> None:
    definition = canonical().model_dump(mode="json")
    definition["nodes"][0]["target"] = {
        "type": "pace_range",
        "min_seconds_per_100m": 100,
        "max_seconds_per_100m": 110,
    }
    definition["nodes"][0]["instructions"] = "Alongar a braçada"

    compiled = GarminWorkoutCompiler().compile(
        revision(CanonicalWorkout.model_validate(definition))
    )

    steps = compiled.payload["workoutSegments"][0]["workoutSteps"]
    pace_step = steps[0]
    assert pace_step["description"] == "Alongar a braçada"
    assert pace_step["secondaryTargetType"] == {
        "workoutTargetTypeId": 6,
        "workoutTargetTypeKey": "pace.zone",
        "displayOrder": 6,
    }
    assert pace_step["secondaryTargetValueOne"] == pytest.approx(100 / 110)
    assert pace_step["secondaryTargetValueTwo"] == pytest.approx(1.0)
    assert pace_step["secondaryTargetValueOne"] < pace_step["secondaryTargetValueTwo"]


def test_compiler_uses_text_fallback_when_native_target_is_not_supported() -> None:
    compiled = GarminWorkoutCompiler(GarminWorkoutCapabilities()).compile(revision(canonical()))

    steps = compiled.payload["workoutSegments"][0]["workoutSteps"]
    work = steps[1]["workoutSteps"][0]
    assert work["description"] == "Respiração bilateral · RPE 5-6"
    assert "secondaryTargetType" not in work
    assert compiled.warnings == ("RPE_TARGET_DOWNGRADED_TO_TEXT",)


def test_compiler_never_silently_drops_a_legacy_named_zone() -> None:
    definition = canonical().model_dump(mode="json")
    definition["nodes"][0]["target"] = {"type": "zone", "zone": "Z2"}
    compiled = GarminWorkoutCompiler(
        GarminWorkoutCapabilities(supports_named_zone_target=True)
    ).compile(revision(CanonicalWorkout.model_validate(definition)))

    step = compiled.payload["workoutSegments"][0]["workoutSteps"][0]
    assert step["description"] == "Zona Z2"
    assert "secondaryTargetType" not in step
    assert "ZONE_TARGET_DOWNGRADED_TO_TEXT" in compiled.warnings


@pytest.mark.parametrize(
    ("minimum", "maximum", "expected"),
    [(1, 1, 1), (2, 2, 2), (3, 4, 3), (5, 6, 4), (7, 8, 5), (9, 9, 6), (10, 10, 7)],
)
def test_rpe_policy_maps_to_the_seven_garmin_effort_categories(
    minimum: int, maximum: int, expected: int
) -> None:
    assert GarminWorkoutCompiler._garmin_effort(minimum, maximum) == expected


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
