from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
import yaml
from mcp.server.auth.provider import AccessToken

from swim_coach.application.services.coach_commands import CoachCommandService
from swim_coach.application.services.mcp_read import McpReadService
from swim_coach.application.services.mcp_write import McpWriteService
from swim_coach.interfaces.mcp.server import create_mcp_server

ROOT = Path(__file__).resolve().parents[3]


class ContractVerifier:
    async def verify_token(self, token: str) -> AccessToken | None:
        del token
        return AccessToken(
            token="",
            client_id="contract",
            scopes=["coach"],
            subject="fixture",
        )


@pytest.mark.asyncio
async def test_v1_list_tools_freezes_the_advertised_envelope_at_1_0() -> None:
    server = create_mcp_server(
        read_service=cast(McpReadService, object()),
        write_service=cast(McpWriteService, object()),
        coach_service=cast(CoachCommandService, object()),
        token_verifier=ContractVerifier(),
        oauth_issuer="https://tenant.example.test",
        oauth_resource="https://swim.example.test/mcp",
        v2_enabled=False,
    )

    listed = await server.list_tools()

    assert listed
    for tool in listed:
        assert tool.outputSchema is not None
        version = tool.outputSchema["properties"]["schema_version"]
        assert version == {
            "const": "1.0",
            "default": "1.0",
            "title": "Schema Version",
            "type": "string",
        }


@pytest.mark.asyncio
async def test_v2_announces_exactly_nine_intent_tools_with_one_scope() -> None:
    contract = yaml.safe_load((ROOT / "contracts/mcp-tools.yaml").read_text())
    assert contract["result_envelope"] == "./tool-result-envelope-v2.schema.json"
    expected = {item["name"]: item for item in contract["tools"]}
    server = create_mcp_server(
        read_service=cast(McpReadService, object()),
        write_service=cast(McpWriteService, object()),
        coach_service=cast(CoachCommandService, object()),
        token_verifier=ContractVerifier(),
        oauth_issuer="https://tenant.example.test",
        oauth_resource="https://swim.example.test/mcp",
        v2_enabled=True,
    )

    registered = server._tool_manager._tools
    assert list(registered) == list(expected)
    assert len(registered) == 9
    assert "nine intent-level tools" in server.instructions
    assert "delete_workout" in server.instructions
    listed = {tool.name: tool for tool in await server.list_tools()}
    assert set(listed) == set(expected)

    for name, tool in registered.items():
        declared = expected[name]
        annotations = declared["annotations"]
        assert tool.annotations is not None
        assert tool.annotations.readOnlyHint is annotations["readOnlyHint"]
        assert tool.annotations.destructiveHint is annotations["destructiveHint"]
        assert tool.annotations.openWorldHint is annotations["openWorldHint"]
        assert tool.parameters["additionalProperties"] is False
        assert set(tool.parameters.get("required", [])) == set(
            declared["input"].get("required", [])
        )
        assert set(tool.parameters["properties"]) == set(declared["input"]["properties"])
        assert tool.output_schema["properties"]["schema_version"]["const"] == "2.0"
        assert listed[name].outputSchema is not None
        assert listed[name].outputSchema["properties"]["schema_version"]["const"] == "2.0"
        assert listed[name].securitySchemes == [{"type": "oauth2", "scopes": ["coach"]}]
        assert listed[name].meta is not None
        assert listed[name].meta["securitySchemes"] == [{"type": "oauth2", "scopes": ["coach"]}]


def test_v2_contract_never_exposes_workflow_protocol_fields() -> None:
    text = (ROOT / "contracts/mcp-tools.yaml").read_text()
    forbidden = (
        "action_hash",
        "proposal_id",
        "approve_action",
        "execute_approved",
        "idempotency_key",
        "expected_revision",
    )
    assert all(item not in text for item in forbidden)
