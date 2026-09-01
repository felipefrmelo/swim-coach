from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from swim_coach.application.queries.get_capabilities import get_capabilities
from swim_coach.application.services.mcp_read import McpResult

ROOT = Path(__file__).resolve().parents[3]


def _schema() -> dict[str, object]:
    return json.loads((ROOT / "contracts/tool-result-envelope.schema.json").read_text())


def test_explicit_v1_mcp_result_conforms_to_frozen_contract() -> None:
    schema = _schema()
    Draft202012Validator.check_schema(schema)
    payload = McpResult(
        schema_version="1.0",
        request_id="request-v1-contract",
        status="OK",
        data={"moving_seconds": "180.0", "pace_seconds_per_100m": "150.0"},
        human_summary="Legacy swim projection.",
    ).model_dump(mode="json")

    Draft202012Validator(schema).validate(payload)
    assert payload["schema_version"] == "1.0"


def test_v1_contract_rejects_default_v2_result() -> None:
    payload = McpResult(
        request_id="request-v2-default",
        status="OK",
        data={},
        human_summary="Canonical result.",
    ).model_dump(mode="json")

    assert payload["schema_version"] == "2.0"
    with pytest.raises(ValidationError):
        Draft202012Validator(_schema()).validate(payload)


def test_p00_capabilities_remain_on_v1_envelope() -> None:
    payload = get_capabilities().model_dump(mode="json")

    Draft202012Validator(_schema()).validate(payload)
    assert payload["schema_version"] == "1.0"
