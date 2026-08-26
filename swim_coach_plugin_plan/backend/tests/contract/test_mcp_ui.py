from __future__ import annotations

from typing import cast

import pytest
from mcp.server.auth.provider import AccessToken

from swim_coach.application.services.mcp_read import (
    MCP_READ_TOOL_SCOPES,
    MCP_READ_TOOLS,
    McpReadService,
    McpResult,
)
from swim_coach.application.services.mcp_write import (
    MCP_WRITE_TOOL_SCOPES,
    MCP_WRITE_TOOLS,
    McpWriteService,
)
from swim_coach.interfaces.mcp.server import create_mcp_server
from swim_coach.interfaces.mcp.ui import (
    MCP_APP_MIME_TYPE,
    MCP_UI_RESOURCE_URIS,
    MCP_UI_TOOL_SCOPES,
    MCP_UI_TOOLS,
    proposal_card,
)

UI_TOOL_KINDS = {
    "render_workout_card": "workout",
    "render_activity_comparison_card": "activity",
    "render_goal_progress_card": "goal",
    "render_proposal_confirmation_card": "proposal",
    "render_sync_status_card": "sync",
}


class UiContractVerifier:
    async def verify_token(self, token: str) -> AccessToken | None:
        del token
        return AccessToken(token="", client_id="ui-contract", scopes=[], subject="fixture")


def ui_server():  # type: ignore[no-untyped-def]
    return create_mcp_server(
        read_service=cast(McpReadService, object()),
        write_service=cast(McpWriteService, object()),
        token_verifier=UiContractVerifier(),
        oauth_issuer="https://tenant.example.test",
        oauth_resource="https://swim.example.test/mcp",
        ui_enabled=True,
        pwa_base_url="https://coach.example.test/app",
    )


@pytest.mark.asyncio
async def test_p09_resources_are_versioned_self_contained_and_closed_by_csp() -> None:
    server = ui_server()
    resources = server._resource_manager.list_resources()

    assert [str(resource.uri) for resource in resources] == list(MCP_UI_RESOURCE_URIS.values())
    assert all(resource.mime_type == MCP_APP_MIME_TYPE for resource in resources)
    for resource in resources:
        assert resource.meta is not None
        assert resource.meta["ui"] == {
            "prefersBorder": True,
            "csp": {"connectDomains": [], "resourceDomains": [], "frameDomains": []},
        }
        assert resource.meta["openai/widgetCSP"]["redirect_domains"] == [
            "https://coach.example.test"
        ]
        contents = list(await server.read_resource(resource.uri))
        assert len(contents) == 1
        html = cast(str, contents[0].content)
        assert "ui/notifications/tool-result" in html
        assert 'request("tools/call"' in html
        assert 'typeof openai.openExternal === "function"' in html
        assert "innerHTML" not in html
        assert "fetch(" not in html
        assert "Authorization" not in html
        assert 'aria-live="polite"' in html
        assert "min-height: 44px" in html


def test_p09_render_tools_are_optional_read_only_and_match_catalog() -> None:
    server = ui_server()
    registered = server._tool_manager._tools
    expected_names = [*MCP_READ_TOOLS, *MCP_WRITE_TOOLS, *MCP_UI_TOOLS]
    assert list(registered) == expected_names
    for name in MCP_UI_TOOLS:
        tool = registered[name]
        assert tool.annotations is not None
        assert tool.annotations.readOnlyHint is True
        assert tool.annotations.destructiveHint is False
        assert tool.annotations.openWorldHint is False
        assert tool.meta is not None
        uri = MCP_UI_RESOURCE_URIS[UI_TOOL_KINDS[name]]
        assert tool.meta["ui"]["resourceUri"] == uri
        assert tool.meta["openai/outputTemplate"] == uri
        assert tool.parameters["additionalProperties"] is False
        assert tool.parameters["properties"]


@pytest.mark.asyncio
async def test_authenticated_tools_advertise_exact_oauth_security_schemes() -> None:
    server = ui_server()
    scope_catalog = {
        **MCP_READ_TOOL_SCOPES,
        **MCP_WRITE_TOOL_SCOPES,
        **MCP_UI_TOOL_SCOPES,
    }

    listed = {tool.name: tool for tool in await server.list_tools()}

    assert set(listed) == set(server._tool_manager._tools)
    for name, tool in listed.items():
        scopes = list(scope_catalog[name])
        security_schemes = [{"type": "oauth2", "scopes": scopes}]
        assert tool.securitySchemes == security_schemes
        assert tool.meta is not None
        assert tool.meta["securitySchemes"] == security_schemes


def test_p09_ui_disabled_preserves_exact_p08_headless_surface() -> None:
    server = create_mcp_server(
        read_service=cast(McpReadService, object()),
        write_service=cast(McpWriteService, object()),
        token_verifier=UiContractVerifier(),
        oauth_issuer="https://tenant.example.test",
        oauth_resource="https://swim.example.test/mcp",
        ui_enabled=False,
    )

    assert list(server._tool_manager._tools) == [*MCP_READ_TOOLS, *MCP_WRITE_TOOLS]
    assert server._resource_manager.list_resources() == []


@pytest.mark.parametrize(
    ("expires_at", "expected_expired", "has_decision"),
    [
        ("2099-01-01T00:00:00+00:00", False, True),
        ("2020-01-01T00:00:00+00:00", True, False),
        ("tampered", True, False),
    ],
)
def test_proposal_card_fails_closed_for_expired_or_invalid_expiry(
    expires_at: str,
    expected_expired: bool,
    has_decision: bool,
) -> None:
    result = McpResult(
        request_id="p09-contract",
        status="OK",
        data={
            "proposal_id": "00000000-0000-0000-0000-000000000909",
            "action_type": "GARMIN_PUBLISH",
            "status": "READY_FOR_REVIEW",
            "action_hash": "a" * 64,
            "expires_at": expires_at,
            "required_action_scope": "garmin:publish",
            "impact": {"distance_m": 1600},
        },
        human_summary="Review exact proposal.",
    )

    card = proposal_card(result).data["card"]
    assert card["expired"] is expected_expired
    assert (card["decision"] is not None) is has_decision
