from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from swim_coach.application.services.mcp_read import (
    McpNextAction,
    McpResult,
    McpWarning,
)

ROOT = Path(__file__).resolve().parents[3]


def _schema() -> dict[str, object]:
    return json.loads((ROOT / "contracts/tool-result-envelope-v2.schema.json").read_text())


def test_mcp_result_serialization_conforms_to_the_v2_json_schema() -> None:
    schema = _schema()
    Draft202012Validator.check_schema(schema)
    payload = McpResult(
        request_id="request-v2-contract",
        status="PARTIAL",
        data={
            "activity_id": "00000000-0000-0000-0000-000000000860",
            "durations": {
                "moving_s": "1699.541",
                "timer_s": "2075.559",
                "elapsed_s": "2089.629",
            },
        },
        warnings=[
            McpWarning(
                code="PACE_FROM_GARMIN_REPORTED_SPEED_DIFFERS_FROM_TIMER_PACE",
                message=(
                    "Pace derived from Garmin-reported speed and timer-derived pace "
                    "are both preserved."
                ),
            )
        ],
        next_actions=[
            McpNextAction(
                action="save_feedback",
                label="Registrar esforço e técnica",
                required_scope="coach",
            )
        ],
        human_summary="Swim data is available with an explicit pace basis.",
    ).model_dump(mode="json")

    Draft202012Validator(schema).validate(payload)

    assert payload["schema_version"] == "2.0"
    assert payload["next_actions"] == [
        {
            "action": "save_feedback",
            "label": "Registrar esforço e técnica",
            "required_scope": "coach",
        }
    ]


def test_v2_envelope_rejects_legacy_schema_version_and_undeclared_fields() -> None:
    validator = Draft202012Validator(_schema())
    valid = McpResult(
        request_id="request-v2-contract",
        status="OK",
        data={},
        human_summary="No data.",
    ).model_dump(mode="json")

    legacy = {**valid, "schema_version": "1.0"}
    with_extra = {**valid, "legacy_pace_seconds_per_100m": "241.344"}

    with pytest.raises(ValidationError):
        validator.validate(legacy)
    with pytest.raises(ValidationError):
        validator.validate(with_extra)


def test_checked_in_latest_swim_example_uses_a_real_v2_action_and_scope() -> None:
    payload = json.loads((ROOT / "examples/tool-result-latest-swim.json").read_text())

    Draft202012Validator(_schema()).validate(payload)
    openapi = yaml.safe_load((ROOT / "contracts/openapi-skeleton.yaml").read_text())
    detail_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$ref": "#/components/schemas/ActivityDetailV2",
        "components": openapi["components"],
    }
    Draft202012Validator(detail_schema).validate(payload["data"])

    assert payload["next_actions"] == [
        {
            "action": "save_feedback",
            "label": "Registrar esforço e técnica",
            "required_scope": "coach",
        }
    ]
