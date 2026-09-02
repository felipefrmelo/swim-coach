"""The retired ruleset planner is not reachable from the application runtime."""

from datetime import UTC, datetime

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server.auth.provider import AccessToken
from sqlalchemy import func, select

from swim_coach.bootstrap.container import build_services
from swim_coach.domain.shared import CorrelationId
from swim_coach.infrastructure.db import Database
from swim_coach.infrastructure.db.models import PlanningRunModel, TrainingDecisionModel
from swim_coach.interfaces.mcp.server import create_mcp_server
from swim_coach.settings import Settings


class CoachTokenVerifier:
    async def verify_token(self, token: str) -> AccessToken | None:
        if token != "coach":  # noqa: S105 - disposable integration marker
            return None
        return AccessToken(
            token="",
            client_id="coach-defined-planning-integration",
            scopes=["coach"],
            expires_at=int(datetime.now(UTC).timestamp()) + 300,
            resource="https://swim.example.test/mcp",
            subject="coach-defined-owner",
        )


async def test_ruleset_generator_is_not_exposed_or_run(
    database: Database, app_settings: Settings
) -> None:
    settings = app_settings.model_copy(
        update={
            "mcp_write_enabled": True,
            "mcp_v2_enabled": True,
            "planning_enabled": True,
        }
    )
    services = build_services(settings, database)
    await services.identity.ensure_identity(
        provider="oidc",
        subject="coach-defined-owner",
        email="first@example.test",
        display_name="Owner",
        claims_snapshot={"email_verified": True},
        correlation_id=CorrelationId.new(),
    )
    server = create_mcp_server(
        read_service=services.mcp_read,
        write_service=services.mcp_write,
        coach_service=services.coach_commands,
        token_verifier=CoachTokenVerifier(),
        oauth_issuer="https://tenant.example.test",
        oauth_resource="https://swim.example.test/mcp",
        v2_enabled=True,
    )
    app = server.streamable_http_app()
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://127.0.0.1",
            headers={"Authorization": "Bearer coach"},
        ) as client:
            async with streamable_http_client("http://127.0.0.1/", http_client=client) as streams:
                async with ClientSession(streams[0], streams[1]) as session:
                    await session.initialize()
                    tool_names = {tool.name for tool in (await session.list_tools()).tools}

    assert "propose_training_plan" in tool_names
    assert "propose_week_plan" not in tool_names
    assert "generate_week" not in tool_names
    async with database.session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(PlanningRunModel)) == 0
        assert await session.scalar(select(func.count()).select_from(TrainingDecisionModel)) == 0
