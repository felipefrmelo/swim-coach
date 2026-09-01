from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from time import perf_counter
from typing import cast

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server.auth.provider import AccessToken
from sqlalchemy import event, func, select

from swim_coach.application.ports.garmin import ActivityFilter, ProviderPage
from swim_coach.application.services import ActivityDataService, GarminSyncService
from swim_coach.application.services.mcp_read import (
    MCP_READ_SCOPES,
    MCP_READ_TOOLS,
    McpPrincipal,
)
from swim_coach.bootstrap.api import create_app
from swim_coach.bootstrap.container import build_services
from swim_coach.domain.shared import CorrelationId
from swim_coach.domain.shared.value_objects import UserId
from swim_coach.domain.workouts import CanonicalWorkout
from swim_coach.infrastructure.db import Database
from swim_coach.infrastructure.db.models import (
    ActivityModel,
    McpToolInvocationModel,
    PlannedWorkoutModel,
)
from swim_coach.infrastructure.storage import FilesystemObjectStorage
from swim_coach.interfaces.mcp.server import create_mcp_server
from swim_coach.settings import Settings

from .test_activity_data import ActivityFileProvider, FixtureParser
from .test_garmin_sync import FixtureGarminProvider, no_op_user_lock
from .test_workout_authoring import canonical_workout


class StaticTokenVerifier:
    def __init__(self, subjects: dict[str, tuple[str, list[str]]]) -> None:
        self._subjects = subjects

    async def verify_token(self, token: str) -> AccessToken | None:
        resolved = self._subjects.get(token)
        if resolved is None:
            return None
        subject, scopes = resolved
        return AccessToken(
            token="",
            client_id="mcp-integration-client",
            scopes=scopes,
            expires_at=int(datetime.now(UTC).timestamp()) + 300,
            resource="https://swim.example.test/mcp",
            subject=subject,
        )


class McpFixtureGarminProvider(FixtureGarminProvider):
    async def list_activities(
        self,
        user_id: UserId,
        cursor: str | None,
        filters: ActivityFilter,
    ) -> ProviderPage:
        page = await super().list_activities(user_id, cursor, filters)
        return ProviderPage(
            tuple(
                replace(
                    item,
                    distance_m=120,
                    elapsed_seconds=Decimal(190),
                    timer_seconds=Decimal(180),
                    moving_seconds=Decimal(180),
                    length_count=6,
                )
                for item in page.items
            ),
            page.next_cursor,
        )


def _tool_error_envelope(text: str) -> dict[str, object]:
    return cast(dict[str, object], json.loads(text[text.index("{") :]))


@pytest.mark.asyncio
async def test_mcp_lists_and_calls_get_capabilities() -> None:
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            async with streamable_http_client(
                "http://127.0.0.1/mcp/",
                http_client=client,
            ) as (read_stream, write_stream, _):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    listed = await session.list_tools()
                    result = await session.call_tool("get_capabilities", {})

    assert [tool.name for tool in listed.tools] == ["get_capabilities"]
    tool = listed.tools[0]
    assert tool.annotations is not None
    assert tool.annotations.readOnlyHint is True
    assert tool.annotations.destructiveHint is False
    assert tool.annotations.openWorldHint is False
    assert result.isError is False
    assert result.structuredContent is not None
    assert result.structuredContent["schema_version"] == "1.0"
    assert result.structuredContent["status"] == "OK"
    assert result.structuredContent["data"]["available_tools"] == ["get_capabilities"]


@pytest.mark.asyncio
async def test_authenticated_mcp_read_tools_scopes_ownership_contract_and_zero_business_writes(
    database: Database,
    app_settings: Settings,
    tmp_path: Path,
) -> None:
    services = build_services(app_settings, database)
    owner = await services.identity.ensure_identity(
        provider="oidc",
        subject="mcp-owner",
        email="first@example.test",
        display_name="Owner",
        claims_snapshot={"email_verified": True},
        correlation_id=CorrelationId.new(),
    )
    other = await services.identity.ensure_identity(
        provider="oidc",
        subject="mcp-other",
        email="second@example.test",
        display_name="Other",
        claims_snapshot={"email_verified": True},
        correlation_id=CorrelationId.new(),
    )
    sync = GarminSyncService(
        services.uow_factory,
        McpFixtureGarminProvider(),
        no_op_user_lock,
        lookback_days=365,
        page_size=2,
    )
    await sync.sync(owner.id, trigger="mcp-test")
    await sync.sync(other.id, trigger="mcp-test")
    pools = await services.context.list_pools(owner.id)
    workout = await services.workouts.create_draft(
        owner.id,
        CanonicalWorkout.model_validate(canonical_workout()),
        pool_id=pools[0].id,
        correlation_id=CorrelationId.new(),
    )
    workout = await services.workouts.approve_local(
        owner.id,
        workout.workout.id,
        expected_version=workout.workout.version,
        expected_content_hash=workout.current_revision.content_hash,
        correlation_id=CorrelationId.new(),
    )
    today = datetime.now(UTC).astimezone().date()
    await services.workouts.schedule(
        owner.id,
        workout.workout.id,
        scheduled_date=today,
        scheduled_start_time=None,
        timezone="America/Sao_Paulo",
        pool_id=pools[0].id,
        expected_version=workout.workout.version,
        correlation_id=CorrelationId.new(),
    )
    async with services.uow_factory() as uow:
        owner_activities = await uow.activities.list_recent(owner.id)
        other_activities = await uow.activities.list_recent(other.id)
    fixture_activity_data = ActivityDataService(
        services.uow_factory,
        ActivityFileProvider(),
        FilesystemObjectStorage(tmp_path / "mcp-artifacts"),
        FixtureParser(),
    )
    await fixture_activity_data.process(owner.id, owner_activities[0].id)

    verifier = StaticTokenVerifier(
        {
            "full": ("mcp-owner", list(MCP_READ_SCOPES)),
            "limited": ("mcp-owner", ["profile:read"]),
            "unlinked": ("not-linked", list(MCP_READ_SCOPES)),
        }
    )
    server = create_mcp_server(
        read_service=services.mcp_read,
        token_verifier=verifier,
        oauth_issuer="https://tenant.example.test",
        oauth_resource="https://swim.example.test/mcp",
    )
    app = server.streamable_http_app()
    transport = httpx.ASGITransport(app=app)
    async with database.session_factory() as db_session:
        activity_count_before = await db_session.scalar(
            select(func.count()).select_from(ActivityModel)
        )
        workout_count_before = await db_session.scalar(
            select(func.count()).select_from(PlannedWorkoutModel)
        )

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as anonymous:
            unauthorized = await anonymous.post(
                "/",
                json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            )
            assert unauthorized.status_code == 401
            assert "resource_metadata=" in unauthorized.headers["www-authenticate"]

        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://127.0.0.1",
            headers={"Authorization": "Bearer full"},
        ) as client:
            async with streamable_http_client("http://127.0.0.1/", http_client=client) as (
                read_stream,
                write_stream,
                _,
            ):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    listed = await session.list_tools()
                    assert [tool.name for tool in listed.tools] == list(MCP_READ_TOOLS)
                    assert all(
                        tool.annotations and tool.annotations.readOnlyHint for tool in listed.tools
                    )
                    assert all(
                        tool.annotations and tool.annotations.openWorldHint is False
                        for tool in listed.tools
                    )
                    assert all(
                        tool.inputSchema.get("additionalProperties") is False
                        for tool in listed.tools
                    )
                    schemas = {tool.name: tool.inputSchema for tool in listed.tools}
                    assert "date" in schemas["get_today_workout"]["properties"]
                    assert schemas["list_recent_swims"]["properties"]["limit"]["maximum"] == 20
                    assert (
                        schemas["get_swim_activity"]["properties"]["max_intervals"]["maximum"]
                        == 100
                    )

                    capabilities = await session.call_tool("get_capabilities", {})
                    training = await session.call_tool("get_training_context", {})
                    today_result = await session.call_tool(
                        "get_today_workout", {"date": today.isoformat()}
                    )
                    week = await session.call_tool("get_week_plan", {})
                    recent = await session.call_tool("list_recent_swims", {"limit": 1})
                    activity = await session.call_tool(
                        "get_swim_activity",
                        {"activity_id": str(owner_activities[0].id)},
                    )
                    progress = await session.call_tool("get_goal_progress", {})
                    sync_status = await session.call_tool("get_sync_status", {})
                    invalid = await session.call_tool(
                        "list_recent_swims", {"limit": 1, "unexpected": True}
                    )
                    invalid_before = await session.call_tool(
                        "list_recent_swims", {"before": "2000-01-01T09:00:00"}
                    )
                    idor = await session.call_tool(
                        "get_swim_activity",
                        {"activity_id": str(other_activities[0].id)},
                    )

        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://127.0.0.1",
            headers={"Authorization": "Bearer limited"},
        ) as client:
            async with streamable_http_client("http://127.0.0.1/", http_client=client) as (
                read_stream,
                write_stream,
                _,
            ):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    missing_scope = await session.call_tool("list_recent_swims", {})

        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://127.0.0.1",
            headers={"Authorization": "Bearer unlinked"},
        ) as client:
            async with streamable_http_client("http://127.0.0.1/", http_client=client) as (
                read_stream,
                write_stream,
                _,
            ):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    unlinked = await session.call_tool("get_capabilities", {})

    successful = [
        capabilities,
        training,
        today_result,
        week,
        recent,
        activity,
        progress,
        sync_status,
    ]
    assert all(result.isError is False and result.structuredContent for result in successful)
    assert all(result.structuredContent["schema_version"] == "1.0" for result in successful)
    assert capabilities.structuredContent["data"]["garmin_write_enabled"] is False
    assert today_result.structuredContent["data"]["workout"]["totals"]["distance_m"] == 1_600
    assert len(recent.structuredContent["data"]["items"]) == 1
    recent_item = recent.structuredContent["data"]["items"][0]
    assert "started_local" in recent_item
    assert "moving_seconds" in recent_item
    assert "pace_seconds_per_100m" in recent_item
    assert "started_at_local" not in recent_item
    assert "durations" not in recent_item
    assert activity.structuredContent["status"] == "OK"
    assert "moving_seconds" in activity.structuredContent["data"]
    assert "pace_seconds_per_100m" in activity.structuredContent["data"]
    assert "durations" not in activity.structuredContent["data"]
    assert "paces" not in activity.structuredContent["data"]
    dimensions = progress.structuredContent["data"]["dimensions"]
    assert set(dimensions) == {"endurance", "pace", "consistency", "confidence"}
    assert (
        dimensions["confidence"]["sample_size"] == progress.structuredContent["data"]["sample_size"]
    )
    serialized = cast(str, activity.content[0].text)
    assert "external_activity_id" not in serialized
    assert '"raw_fit":' not in serialized
    assert "raw_fit_exposed" not in serialized
    assert "input_checksum" not in serialized
    assert invalid.isError is True
    assert invalid_before.isError is True
    assert _tool_error_envelope(invalid_before.content[0].text)["schema_version"] == "1.0"
    assert idor.isError is True
    assert "RESOURCE_NOT_FOUND" in idor.content[0].text
    assert _tool_error_envelope(idor.content[0].text)["schema_version"] == "1.0"
    assert missing_scope.isError is True
    assert "SCOPE_REQUIRED" in missing_scope.content[0].text
    assert missing_scope.structuredContent is not None
    assert missing_scope.structuredContent["schema_version"] == "1.0"
    assert _tool_error_envelope(missing_scope.content[0].text)["schema_version"] == "1.0"
    assert unlinked.isError is True
    assert "ACCOUNT_DISABLED" in unlinked.content[0].text
    assert _tool_error_envelope(unlinked.content[0].text)["schema_version"] == "1.0"

    async with database.session_factory() as db_session:
        assert (
            await db_session.scalar(select(func.count()).select_from(ActivityModel))
            == activity_count_before
        )
        assert (
            await db_session.scalar(select(func.count()).select_from(PlannedWorkoutModel))
            == workout_count_before
        )
        invocation_count = await db_session.scalar(
            select(func.count()).select_from(McpToolInvocationModel)
        )
        hashes = list(await db_session.scalars(select(McpToolInvocationModel.args_hash)))
    assert invocation_count == 9
    assert hashes and all(len(value) == 64 for value in hashes)

    query_log: list[str] = []

    def count_query(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        query_log.append(statement)

    event.listen(database.engine.sync_engine, "before_cursor_execute", count_query)
    principal = McpPrincipal(owner.id, "mcp-owner", frozenset(MCP_READ_SCOPES))
    try:
        start_index = len(query_log)
        await services.mcp_read.list_recent_swims(
            principal,
            "performance-list",
            limit=20,
            before=None,
            include_analysis_summary=True,
        )
        recent_query_count = len(query_log) - start_index
        start_index = len(query_log)
        await services.mcp_read.get_week_plan(principal, "performance-week", week_start=None)
        week_query_count = len(query_log) - start_index
        timings_ms: list[float] = []
        for index in range(30):
            started_at = perf_counter()
            await services.mcp_read.list_recent_swims(
                principal,
                f"performance-{index}",
                limit=20,
                before=None,
                include_analysis_summary=True,
            )
            timings_ms.append((perf_counter() - started_at) * 1_000)
    finally:
        event.remove(database.engine.sync_engine, "before_cursor_execute", count_query)
    p95_ms = sorted(timings_ms)[int(len(timings_ms) * 0.95) - 1]
    # Activity, canonical normalization, manual feedback overrides and analysis
    # are fetched in four bounded queries; the count does not grow with the page.
    assert recent_query_count == 4
    assert week_query_count <= 5
    assert p95_ms < 500
