import json
from pathlib import Path

from jsonschema import Draft202012Validator

from swim_coach.domain.workouts import CanonicalWorkout, validate_workout
from swim_coach.domain.workouts.schema import ValidationIssue


def workout_payload() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "title": "Técnica 200 m",
        "sport": "POOL_SWIMMING",
        "pool_length_m": 20,
        "purpose": "TECHNIQUE",
        "nodes": [
            {
                "type": "step",
                "step_role": "DRILL",
                "end_condition": {"type": "distance", "meters": 200},
            }
        ],
    }


def test_runtime_model_matches_checked_in_contract_for_fixture() -> None:
    payload = workout_payload()
    schema = json.loads(Path("contracts/canonical-workout.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(payload)
    assert CanonicalWorkout.model_validate(payload).schema_version == "1.0"


def test_validation_issue_is_strict() -> None:
    issue = ValidationIssue(code="EXAMPLE", path="/nodes", message="example")
    assert issue.model_dump() == {"code": "EXAMPLE", "path": "/nodes", "message": "example"}


def test_all_p04_workout_fixtures_validate_and_end_at_the_wall() -> None:
    schema = json.loads(Path("contracts/canonical-workout.schema.json").read_text())
    fixtures = sorted(Path("examples/workouts").glob("*.json"))
    assert {item.stem for item in fixtures} == {
        "endurance-1600m",
        "speed-1000m",
        "technique-800m",
        "test-1200m",
    }
    for fixture in fixtures:
        payload = json.loads(fixture.read_text())
        Draft202012Validator(schema).validate(payload)
        definition = CanonicalWorkout.model_validate(payload)
        result = validate_workout(definition)
        assert result.valid, (fixture, result.errors)
        assert result.totals.distance_m % definition.pool_length_m == 0
