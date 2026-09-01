"""P10 deterministic planning persistence, replay and approval boundaries."""

from datetime import UTC, date, datetime, time

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server.auth.provider import AccessToken
from sqlalchemy import func, select

from swim_coach.application.services.context import AvailabilityInput
from swim_coach.application.services.mcp_read import McpPrincipal
from swim_coach.bootstrap.container import build_services
from swim_coach.domain.planning import FeedbackSnapshot, PlanningContext
from swim_coach.domain.shared import CorrelationId
from swim_coach.domain.shared.errors import ResourceNotFoundError
from swim_coach.domain.shared.value_objects import EntityId, UserId
from swim_coach.infrastructure.db import Database
from swim_coach.infrastructure.db.models import (
    ActionProposalModel,
    PlannedWorkoutModel,
    PlanningRunModel,
    TrainingDecisionModel,
    TrainingRuleSetModel,
    WorkoutScheduleModel,
)
from swim_coach.interfaces.mcp.server import create_mcp_server
from swim_coach.settings import Settings


class PlanningTokenVerifier:
    async def verify_token(self, token: str) -> AccessToken | None:
        if token != "full":  # noqa: S105 - disposable integration marker
            return None
        return AccessToken(
            token="",
            client_id="planning-integration",
            scopes=["planning:write", "proposals:write", "proposals:approve"],
            expires_at=int(datetime.now(UTC).timestamp()) + 300,
            resource="https://swim.example.test/mcp",
            subject="planning-owner",
        )


async def test_week_proposal_is_reproducible_owned_and_never_applied_by_approval(
    database: Database, app_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = app_settings.model_copy(
        update={
            "oauth_issuer": "https://tenant.example.test",
            "oauth_resource": "https://swim.example.test/mcp",
            "mcp_write_enabled": True,
            "planning_enabled": True,
        }
    )
    services = build_services(settings, database)
    owner = await services.identity.ensure_identity(
        provider="oidc",
        subject="planning-owner",
        email="first@example.test",
        display_name="Owner",
        claims_snapshot={"email_verified": True},
        correlation_id=CorrelationId.new(),
    )
    other = await services.identity.ensure_identity(
        provider="oidc",
        subject="planning-other",
        email="second@example.test",
        display_name="Other",
        claims_snapshot={"email_verified": True},
        correlation_id=CorrelationId.new(),
    )
    pools = await services.context.list_pools(owner.id)
    await services.context.replace_availability(
        owner.id,
        [
            AvailabilityInput(0, time(7), time(8), 60, pools[0].id),
            AvailabilityInput(2, time(7), time(8), 60, pools[0].id),
            AvailabilityInput(5, time(9), time(10, 15), 75, pools[0].id),
        ],
        correlation_id=CorrelationId.new(),
    )
    principal = McpPrincipal(
        owner.id,
        "planning-owner",
        frozenset({"planning:write", "proposals:write", "proposals:approve"}),
    )
    other_principal = McpPrincipal(
        other.id,
        "planning-other",
        principal.scopes,
    )
    assert services.mcp_write is not None
    assert services.planning is not None
    original_snapshot = services.planning._snapshot

    async def snapshot_with_low_august_feeling(
        user_id: UserId, week_start: date
    ) -> PlanningContext:
        snapshot = await original_snapshot(user_id, week_start)
        return snapshot.model_copy(
            update={
                "recent_feedback": (
                    FeedbackSnapshot(
                        activity_id="00000000-0000-0000-0000-000000001099",
                        activity_date=date(2026, 8, 15),
                        rpe=None,
                        feeling_score=5,
                        feeling_score_source="GARMIN",
                        pain_present=False,
                    ),
                )
            }
        )

    monkeypatch.setattr(services.planning, "_snapshot", snapshot_with_low_august_feeling)

    first = await services.mcp_write.propose_week_plan(
        principal,
        "planning-request-1",
        week_start=date(2026, 8, 17),
        constraints={"session_count": 3, "focus": "GOAL_PACE"},
        user_notes="Prefiro treinos de manhã.",
        correlation_id=CorrelationId.new(),
    )
    replay = await services.mcp_write.propose_week_plan(
        principal,
        "planning-request-2",
        week_start=date(2026, 8, 17),
        constraints={"session_count": 3, "focus": "GOAL_PACE"},
        user_notes="Texto diferente não é persistido nem muda a entrada canônica.",
        correlation_id=CorrelationId.new(),
    )

    assert first.data["replayed"] is False
    assert replay.data["replayed"] is True
    assert replay.data["planning_run_id"] == first.data["planning_run_id"]
    assert replay.data["proposal_id"] == first.data["proposal_id"]
    week = first.data["week"]
    assert "LOW_SESSION_FEELING_RECOVERY_BIAS" not in week["warnings"]
    assert all(item["rule_id"] != "RULE-FEELING-001" for item in week["decisions"])
    assert len(week["sessions"]) == 3
    assert [item["order"] for item in week["decisions"]] == list(
        range(1, len(week["decisions"]) + 1)
    )
    assert first.data["impact"]["external_effects"] == []

    server = create_mcp_server(
        read_service=services.mcp_read,
        write_service=services.mcp_write,
        token_verifier=PlanningTokenVerifier(),
        oauth_issuer="https://tenant.example.test",
        oauth_resource="https://swim.example.test/mcp",
    )
    app = server.streamable_http_app()
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://127.0.0.1",
            headers={"Authorization": "Bearer full"},
        ) as client:
            async with streamable_http_client("http://127.0.0.1/", http_client=client) as streams:
                async with ClientSession(streams[0], streams[1]) as session:
                    await session.initialize()
                    tools = {item.name: item for item in (await session.list_tools()).tools}
                    planning_schema = tools["propose_week_plan"].inputSchema
                    constraints_schema = planning_schema["properties"]["constraints"]
                    preferences_ref = next(
                        item["$ref"] for item in constraints_schema["anyOf"] if "$ref" in item
                    )
                    preferences_name = preferences_ref.rsplit("/", 1)[-1]
                    assert (
                        planning_schema["$defs"][preferences_name]["additionalProperties"] is False
                    )
                    capabilities = await session.call_tool("get_capabilities", {})
                    via_mcp = await session.call_tool(
                        "propose_week_plan",
                        {
                            "week_start": "2026-08-17",
                            "constraints": {"session_count": 3, "focus": "GOAL_PACE"},
                            "user_notes": "Notas diferentes continuam fora do snapshot.",
                        },
                    )
    assert capabilities.isError is False
    assert capabilities.structuredContent["data"]["phase"] == "P10"
    assert capabilities.structuredContent["data"]["server_version"] == ("0.4.0-adaptive-planning")
    assert via_mcp.isError is False
    assert via_mcp.structuredContent["data"]["replayed"] is True
    assert via_mcp.structuredContent["data"]["planning_run_id"] == first.data["planning_run_id"]

    async with services.uow_factory() as uow:
        decision_records = await uow.training_decisions.list_for_run(
            owner.id, EntityId.parse(first.data["planning_run_id"])
        )
    assert [item.order_index for item in decision_records] == list(
        range(1, len(decision_records) + 1)
    )

    async with database.session_factory() as session:
        before_workouts = await session.scalar(
            select(func.count()).select_from(PlannedWorkoutModel)
        )
        before_schedules = await session.scalar(
            select(func.count()).select_from(WorkoutScheduleModel)
        )
        stored_ruleset = (
            await session.scalars(
                select(TrainingRuleSetModel).where(
                    TrainingRuleSetModel.version == "1.0.0",
                    TrainingRuleSetModel.effective_from == date(2026, 8, 12),
                )
            )
        ).one()
        assert stored_ruleset.version == "1.0.0"
        assert stored_ruleset.effective_from == date(2026, 8, 12)
        assert "low_feeling_threshold" not in stored_ruleset.rules_json
        assert await session.scalar(select(func.count()).select_from(PlanningRunModel)) == 1
        assert await session.scalar(select(func.count()).select_from(ActionProposalModel)) == 1
        proposal_revision = await session.scalar(select(ActionProposalModel.target_revision_id))
        assert proposal_revision is None
        decision_count = await session.scalar(
            select(func.count()).select_from(TrainingDecisionModel)
        )
        assert decision_count == len(week["decisions"])

    with pytest.raises(ResourceNotFoundError):
        await services.mcp_write.get_action_proposal(
            other_principal,
            "planning-idor",
            EntityId.parse(first.data["proposal_id"]),
        )

    approved = await services.mcp_write.approve_action_proposal(
        principal,
        "planning-approval",
        proposal_id=EntityId.parse(first.data["proposal_id"]),
        expected_action_hash=first.data["action_hash"],
        decision="APPROVE",
        confirmation_text="Aprovo somente a proposta exibida para revisão.",
        correlation_id=CorrelationId.new(),
    )
    assert approved.data["status"] == "APPROVED"
    assert approved.data["execution"] is None

    async with database.session_factory() as session:
        assert (
            await session.scalar(select(func.count()).select_from(PlannedWorkoutModel))
            == before_workouts
        )
        assert (
            await session.scalar(select(func.count()).select_from(WorkoutScheduleModel))
            == before_schedules
        )
