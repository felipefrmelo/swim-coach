from __future__ import annotations

from pathlib import Path
from typing import cast

import yaml
from mcp.server.auth.provider import AccessToken

from swim_coach.application.services.mcp_read import MCP_READ_TOOLS, McpReadService
from swim_coach.application.services.mcp_write import (
    MCP_PLANNING_TOOLS,
    MCP_WRITE_TOOLS,
    McpWriteService,
)
from swim_coach.interfaces.mcp.server import create_mcp_server

ROOT = Path(__file__).resolve().parents[3]


class ContractVerifier:
    async def verify_token(self, token: str) -> AccessToken | None:
        del token
        return AccessToken(token="", client_id="contract", scopes=[], subject="fixture")


class PlanningWriteContractStub:
    planning_enabled = True


def _types(schema: dict[str, object]) -> set[str]:
    direct = schema.get("type")
    if isinstance(direct, str):
        return {direct}
    if isinstance(direct, list):
        return {str(item) for item in direct}
    variants = schema.get("anyOf")
    if isinstance(variants, list):
        return {str(item["type"]) for item in variants if isinstance(item, dict) and "type" in item}
    return set()


def test_p05_tool_schemas_and_annotations_match_versioned_contract() -> None:
    contract = yaml.safe_load((ROOT / "contracts/mcp-tools.yaml").read_text())
    expected = {item["name"]: item for item in contract["tools"] if item["name"] in MCP_READ_TOOLS}
    server = create_mcp_server(
        read_service=cast(McpReadService, object()),
        token_verifier=ContractVerifier(),
        oauth_issuer="https://tenant.example.test",
        oauth_resource="https://swim.example.test/mcp",
    )
    registered = server._tool_manager._tools

    assert list(registered) == list(MCP_READ_TOOLS)
    assert set(registered) == set(expected)
    for name, tool in registered.items():
        declared = expected[name]
        annotations = declared["annotations"]
        assert tool.annotations is not None
        assert tool.annotations.readOnlyHint is annotations["readOnlyHint"] is True
        assert tool.annotations.destructiveHint is annotations["destructiveHint"] is False
        assert tool.annotations.openWorldHint is annotations["openWorldHint"] is False
        assert tool.parameters["additionalProperties"] is False
        declared_input = declared["input"]
        assert set(tool.parameters.get("required", [])) == set(declared_input.get("required", []))
        actual_properties = tool.parameters["properties"]
        declared_properties = declared_input["properties"]
        assert set(actual_properties) == set(declared_properties)
        for property_name, property_contract in declared_properties.items():
            actual = actual_properties[property_name]
            assert _types(actual) == _types(property_contract)
            for constraint in ("minimum", "maximum", "default"):
                if constraint in property_contract:
                    assert actual[constraint] == property_contract[constraint]

        output = tool.fn_metadata.output_schema
        assert output is not None
        assert output["additionalProperties"] is False
        assert set(output["properties"]) == {
            "schema_version",
            "request_id",
            "status",
            "data",
            "warnings",
            "next_actions",
            "human_summary",
        }


def test_p08_controlled_write_tools_match_contract_and_risk_annotations() -> None:
    contract = yaml.safe_load((ROOT / "contracts/mcp-tools.yaml").read_text())
    selected = set((*MCP_READ_TOOLS, *MCP_WRITE_TOOLS))
    expected = {item["name"]: item for item in contract["tools"] if item["name"] in selected}
    server = create_mcp_server(
        read_service=cast(McpReadService, object()),
        write_service=cast(McpWriteService, object()),
        token_verifier=ContractVerifier(),
        oauth_issuer="https://tenant.example.test",
        oauth_resource="https://swim.example.test/mcp",
    )
    registered = server._tool_manager._tools

    assert list(registered) == [*MCP_READ_TOOLS, *MCP_WRITE_TOOLS]
    assert set(registered) == set(expected)
    for name in MCP_WRITE_TOOLS:
        tool = registered[name]
        declared = expected[name]
        annotations = declared["annotations"]
        assert tool.annotations is not None
        assert tool.annotations.readOnlyHint is annotations["readOnlyHint"]
        assert tool.annotations.destructiveHint is annotations["destructiveHint"]
        assert tool.annotations.openWorldHint is annotations["openWorldHint"]
        assert tool.parameters["additionalProperties"] is False
        declared_input = declared["input"]
        assert set(tool.parameters.get("required", [])) == set(declared_input.get("required", []))
        assert set(tool.parameters["properties"]) == set(declared_input["properties"])


def test_p10_planning_tool_matches_closed_versioned_contract() -> None:
    contract = yaml.safe_load((ROOT / "contracts/mcp-tools.yaml").read_text())
    declared = next(item for item in contract["tools"] if item["name"] == "propose_week_plan")
    server = create_mcp_server(
        read_service=cast(McpReadService, object()),
        write_service=cast(McpWriteService, PlanningWriteContractStub()),
        token_verifier=ContractVerifier(),
        oauth_issuer="https://tenant.example.test",
        oauth_resource="https://swim.example.test/mcp",
    )
    registered = server._tool_manager._tools

    assert set(MCP_PLANNING_TOOLS) <= set(registered)
    tool = registered["propose_week_plan"]
    assert tool.annotations is not None
    assert tool.annotations.readOnlyHint is declared["annotations"]["readOnlyHint"] is False
    assert tool.annotations.destructiveHint is declared["annotations"]["destructiveHint"] is False
    assert tool.annotations.openWorldHint is declared["annotations"]["openWorldHint"] is False
    assert tool.parameters["additionalProperties"] is False
    assert set(tool.parameters.get("required", [])) == {"week_start"}
    assert set(tool.parameters["properties"]) == set(declared["input"]["properties"])
    constraints = tool.parameters["properties"]["constraints"]
    preferences_ref = next(item["$ref"] for item in constraints["anyOf"] if "$ref" in item)
    preferences = tool.parameters["$defs"][preferences_ref.rsplit("/", 1)[-1]]
    assert preferences["additionalProperties"] is False
    assert set(preferences["properties"]) == set(
        declared["input"]["properties"]["constraints"]["properties"]
    )
