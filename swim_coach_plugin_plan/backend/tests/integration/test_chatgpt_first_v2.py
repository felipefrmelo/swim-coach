import json
from datetime import UTC, date, datetime, time, timedelta

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server.auth.provider import AccessToken
from sqlalchemy import func, select, update

from swim_coach.application.services.context import AvailabilityInput
from swim_coach.bootstrap.api import create_app
from swim_coach.bootstrap.container import build_services
from swim_coach.domain.athlete import Device
from swim_coach.domain.shared import CorrelationId
from swim_coach.domain.shared.value_objects import EntityId, UserId
from swim_coach.domain.workouts import PlannedWorkoutStatus
from swim_coach.infrastructure.db import Database
from swim_coach.infrastructure.db.models import (
    ActionApprovalModel,
    ActionExecutionModel,
    ActionProposalModel,
    ExternalWorkoutBindingModel,
    JobModel,
    PlanReviewModel,
    PlanSessionBindingModel,
    TrainingPlanRevisionModel,
    WorkoutScheduleModel,
)
from swim_coach.infrastructure.garmin import FakeGarminWorkoutProvider
from swim_coach.interfaces.mcp.server import create_mcp_server
from swim_coach.interfaces.worker.main import Worker
from swim_coach.settings import Settings

from .test_workout_authoring import canonical_workout


def plan_workout(distance_m: int, purpose: str) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "title": f"{purpose.title()} {distance_m} m",
        "sport": "POOL_SWIMMING",
        "pool_length_m": 20,
        "purpose": purpose,
        "tags": ["coach-defined"],
        "nodes": [
            {
                "type": "step",
                "step_role": "WORK",
                "end_condition": {"type": "distance", "meters": distance_m},
                "target": {
                    "type": "pace_range",
                    "min_seconds_per_100m": 130,
                    "max_seconds_per_100m": 140,
                },
                "stroke": {"type": "freestyle"},
                "equipment": [],
            }
        ],
    }


def coach_plan_definition(
    *, goal_id: EntityId, start_date: date, pool_id: EntityId
) -> dict[str, object]:
    weeks: list[dict[str, object]] = [
        {
            "week_number": 1,
            "focus": "Technique and endurance",
            "detail_level": "DETAILED",
            "coach_rationale": "Establish two explicit coach-authored sessions.",
            "session_count": 2,
            "load_target": "BUILD",
            "sessions": [
                {
                    "session_number": 1,
                    "purpose": "TECHNIQUE",
                    "objective": "Technique over 1,000 m.",
                    "coach_rationale": "Practice stable form.",
                    "target_distance_m": 1_000,
                    "planned_duration_minutes": 45,
                    "intensity": "MODERATE",
                    "scheduled_date": (start_date + timedelta(days=1)).isoformat(),
                    "scheduled_start_time": "06:15",
                    "pool_id": str(pool_id),
                    "key_set": "Coach-authored 1,000 m technique session",
                    "workout": plan_workout(1_000, "TECHNIQUE"),
                },
                {
                    "session_number": 2,
                    "purpose": "ENDURANCE",
                    "objective": "Endurance over 1,100 m.",
                    "coach_rationale": "Practice aerobic continuity.",
                    "target_distance_m": 1_100,
                    "planned_duration_minutes": 45,
                    "intensity": "MODERATE",
                    "scheduled_date": (start_date + timedelta(days=3)).isoformat(),
                    "scheduled_start_time": "06:15",
                    "pool_id": str(pool_id),
                    "key_set": "Coach-authored 1,100 m endurance session",
                    "workout": plan_workout(1_100, "ENDURANCE"),
                },
            ],
        }
    ]
    weeks.extend(
        {
            "week_number": number,
            "focus": "Coach-defined strategic horizon",
            "detail_level": "STRATEGIC",
            "coach_rationale": "The coach will author details in a future revision.",
            "sessions": [],
        }
        for number in range(2, 9)
    )
    return {
        "schema_version": "2.0",
        "goal_id": str(goal_id),
        "title": "2,000 m in 45 minutes · 8 weeks",
        "start_date": start_date.isoformat(),
        "timezone": "America/Sao_Paulo",
        "prescription_source": "COACH_DEFINED",
        "strategy_summary": "Coach-authored eight-week strategy.",
        "review_frequency": "WEEKLY",
        "duration_weeks": 8,
        "phases": [],
        "weeks": weeks,
    }


class CoachTokenVerifier:
    async def verify_token(self, token: str) -> AccessToken | None:
        if token != "coach-token":  # noqa: S105 - disposable integration marker
            return None
        return AccessToken(
            token="",
            client_id="chatgpt-test",
            scopes=["coach"],
            expires_at=int(datetime.now(UTC).timestamp()) + 300,
            resource="https://swim.example.test/mcp",
            subject="chatgpt-v2-owner",
        )


async def test_mcp_v2_calls_direct_save_without_protocol_fields(
    database: Database, app_settings: Settings
) -> None:
    settings = app_settings.model_copy(
        update={
            "garmin_write_enabled": True,
            "garmin_write_mode": "fake",
            "mcp_write_enabled": True,
            "mcp_v2_enabled": True,
            "planning_enabled": True,
        }
    )
    services = build_services(settings, database)
    owner = await services.identity.ensure_identity(
        provider="oidc",
        subject="chatgpt-v2-owner",
        email="first@example.test",
        display_name="ChatGPT owner",
        claims_snapshot={"email_verified": True},
        correlation_id=CorrelationId.new(),
    )
    pools = await services.context.list_pools(owner.id)
    await services.context.replace_availability(
        owner.id,
        [
            AvailabilityInput(1, time(6, 15), time(7), 45, pools[0].id),
            AvailabilityInput(3, time(6, 15), time(7), 45, pools[0].id),
        ],
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
    target_date = date.today() + timedelta(days=2)
    next_monday = target_date + timedelta(days=(7 - target_date.weekday()) % 7)
    goals = await services.context.list_goals(owner.id)
    active_goal = next(item for item in goals if item.status.value == "active")
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://127.0.0.1",
            headers={"Authorization": "Bearer coach-token"},
        ) as client:
            async with streamable_http_client("http://127.0.0.1/", http_client=client) as (
                read_stream,
                write_stream,
                _,
            ):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    listed = await session.list_tools()
                    assert [tool.name for tool in listed.tools] == [
                        "get_coach_context",
                        "propose_training_plan",
                        "get_training_plan",
                        "review_training_plan",
                        "propose_plan_revision",
                        "apply_plan_revision",
                        "add_plan_note",
                        "set_training_plan_status",
                        "skip_plan_session",
                        "get_workouts",
                        "get_swims",
                        "save_workout",
                        "publish_workout",
                        "delete_workout",
                        "materialize_plan_week",
                        "sync_garmin",
                        "save_feedback",
                    ]
                    assert all(
                        tool.meta
                        and tool.meta.get("securitySchemes")
                        == [{"type": "oauth2", "scopes": ["coach"]}]
                        for tool in listed.tools
                    )
                    definition = canonical_workout()
                    nodes = definition["nodes"]
                    assert isinstance(nodes, list)
                    first_step = nodes[0]
                    assert isinstance(first_step, dict)
                    first_step["target"] = {"type": "rpe", "min": 5, "max": 6}
                    saved = await session.call_tool(
                        "save_workout",
                        {
                            "pool_id": str(pools[0].id),
                            "definition": definition,
                            "scheduled_date": target_date.isoformat(),
                            "scheduled_start_time": "19:00:00",
                        },
                    )
                    assert saved.structuredContent is not None
                    published = await session.call_tool(
                        "publish_workout",
                        {"workout_id": saved.structuredContent["data"]["workout_id"]},
                    )
                    workouts = await session.call_tool(
                        "get_workouts", {"date": target_date.isoformat()}
                    )
                    swims = await session.call_tool("get_swims", {})
                    missing_swim = await session.call_tool(
                        "get_swims", {"activity_id": str(EntityId.new())}
                    )
                    proposed_plan = await session.call_tool(
                        "propose_training_plan",
                        {
                            "definition": coach_plan_definition(
                                goal_id=active_goal.id,
                                start_date=next_monday,
                                pool_id=pools[0].id,
                            ),
                        },
                    )
                    assert proposed_plan.structuredContent is not None
                    plan_data = proposed_plan.structuredContent["data"]
                    proposed_sessions = plan_data["plan"]["weeks"][0]["sessions"]
                    assert len(proposed_sessions) == 2
                    assert [item["scheduled_date"] for item in proposed_sessions] == [
                        (next_monday + timedelta(days=1)).isoformat(),
                        (next_monday + timedelta(days=3)).isoformat(),
                    ]
                    assert [item["target_distance_m"] for item in proposed_sessions] == [
                        1_000,
                        1_100,
                    ]
                    stale_apply = await session.call_tool(
                        "apply_plan_revision",
                        {
                            "plan_id": plan_data["plan_id"],
                            "proposal_id": plan_data["proposal_id"],
                            "expected_revision": 1,
                            "approval_hash": plan_data["action_hash"],
                        },
                    )
                    tampered_apply = await session.call_tool(
                        "apply_plan_revision",
                        {
                            "plan_id": plan_data["plan_id"],
                            "proposal_id": plan_data["proposal_id"],
                            "expected_revision": 0,
                            "approval_hash": "0" * 64,
                        },
                    )
                    applied_plan = await session.call_tool(
                        "apply_plan_revision",
                        {
                            "plan_id": plan_data["plan_id"],
                            "proposal_id": plan_data["proposal_id"],
                            "expected_revision": 0,
                            "approval_hash": plan_data["action_hash"],
                        },
                    )
                    generated = await session.call_tool(
                        "materialize_plan_week",
                        {
                            "plan_id": plan_data["plan_id"],
                            "expected_revision": 1,
                            "week_number": 1,
                        },
                    )
                    generated_replay = await session.call_tool(
                        "materialize_plan_week",
                        {
                            "plan_id": plan_data["plan_id"],
                            "expected_revision": 1,
                            "week_number": 1,
                        },
                    )
                    added_note = await session.call_tool(
                        "add_plan_note",
                        {
                            "plan_id": plan_data["plan_id"],
                            "scope_type": "PLAN",
                            "scope_ref": plan_data["plan_id"],
                            "category": "DECISION",
                            "author_type": "COACH",
                            "text": "Consolidar antes de aumentar a carga.",
                        },
                    )
                    loaded_plan = await session.call_tool(
                        "get_training_plan", {"plan_id": plan_data["plan_id"]}
                    )
                    skipped_sessions = [
                        await session.call_tool(
                            "skip_plan_session",
                            {
                                "plan_id": plan_data["plan_id"],
                                "session_intent_id": item["session_intent_id"],
                            },
                        )
                        for item in generated.structuredContent["data"]["sessions"]
                    ]
                    plan_review = await session.call_tool(
                        "review_training_plan",
                        {"plan_id": plan_data["plan_id"], "week_number": 1},
                    )
                    assert plan_review.structuredContent is not None
                    detailed_week_two = {
                        **plan_data["plan"]["weeks"][1],
                        "detail_level": "DETAILED",
                        "session_count": 1,
                        "sessions": [
                            {
                                "session_number": 1,
                                "purpose": "ENDURANCE",
                                "objective": "Materialize the coach-authored second week.",
                                "coach_rationale": "Explicit rolling-horizon detail.",
                                "target_distance_m": 800,
                                "planned_duration_minutes": 45,
                                "intensity": "MODERATE",
                                "scheduled_date": (next_monday + timedelta(days=8)).isoformat(),
                                "scheduled_start_time": "06:15",
                                "pool_id": str(pools[0].id),
                                "key_set": "Coach-authored 800 m endurance session",
                                "workout": plan_workout(800, "ENDURANCE"),
                            }
                        ],
                    }
                    materialized_definition = {
                        **plan_data["plan"],
                        "weeks": [
                            plan_data["plan"]["weeks"][0],
                            detailed_week_two,
                            *plan_data["plan"]["weeks"][2:],
                        ],
                    }
                    materialization_proposal = await session.call_tool(
                        "propose_plan_revision",
                        {
                            "plan_id": plan_data["plan_id"],
                            "expected_revision": 1,
                            "revision_definition": {
                                "schema_version": "1.0",
                                "kind": "MATERIALIZATION",
                                "rationale": "Detail week two exactly as prescribed.",
                                "definition": materialized_definition,
                            },
                        },
                    )
                    assert materialization_proposal.structuredContent is not None
                    materialization_data = materialization_proposal.structuredContent["data"]
                    applied_materialization = await session.call_tool(
                        "apply_plan_revision",
                        {
                            "plan_id": plan_data["plan_id"],
                            "proposal_id": materialization_data["proposal_id"],
                            "expected_revision": 1,
                            "approval_hash": materialization_data["action_hash"],
                        },
                    )
                    generated_week_two = await session.call_tool(
                        "materialize_plan_week",
                        {
                            "plan_id": plan_data["plan_id"],
                            "expected_revision": 2,
                            "week_number": 2,
                        },
                    )
                    review_after_materialization = await session.call_tool(
                        "review_training_plan",
                        {"plan_id": plan_data["plan_id"], "week_number": 1},
                    )
                    assert review_after_materialization.structuredContent is not None
                    review_data = review_after_materialization.structuredContent["data"]
                    revision_proposal = await session.call_tool(
                        "propose_plan_revision",
                        {
                            "plan_id": plan_data["plan_id"],
                            "expected_revision": 2,
                            "revision_definition": {
                                "schema_version": "1.0",
                                "kind": "ADAPTATION",
                                "review_id": review_data["review_id"],
                                "decision": "HOLD",
                                "rationale": "Consolidar após duas sessões ignoradas.",
                                "definition": {
                                    **materialized_definition,
                                    "weeks": [
                                        materialized_definition["weeks"][0],
                                        {
                                            **materialized_definition["weeks"][1],
                                            "focus": "Coach explicitly holds the strategy",
                                            "detail_level": "STRATEGIC",
                                            "session_count": 0,
                                            "sessions": [],
                                        },
                                        *materialized_definition["weeks"][2:],
                                    ],
                                },
                            },
                        },
                    )
                    assert revision_proposal.structuredContent is not None
                    revision_data = revision_proposal.structuredContent["data"]
                    applied_revision = await session.call_tool(
                        "apply_plan_revision",
                        {
                            "plan_id": plan_data["plan_id"],
                            "proposal_id": revision_data["proposal_id"],
                            "expected_revision": 2,
                            "approval_hash": revision_data["action_hash"],
                        },
                    )
                    loaded_after_revision = await session.call_tool(
                        "get_training_plan", {"plan_id": plan_data["plan_id"]}
                    )

    assert saved.isError is False
    assert saved.structuredContent is not None
    assert all(
        result.structuredContent is not None and result.structuredContent["schema_version"] == "2.0"
        for result in (
            saved,
            published,
            workouts,
            swims,
            proposed_plan,
            applied_plan,
            generated,
            generated_replay,
            added_note,
            loaded_plan,
            *skipped_sessions,
            plan_review,
            materialization_proposal,
            applied_materialization,
            generated_week_two,
            review_after_materialization,
            revision_proposal,
            applied_revision,
            loaded_after_revision,
        )
    )
    assert saved.structuredContent["data"]["status"] == "scheduled"
    assert workouts.isError is False
    assert workouts.structuredContent is not None
    assert published.isError is False
    assert published.structuredContent is not None
    assert published.structuredContent["warnings"] == [
        {
            "code": "RPE_TARGET_MAPPED_TO_GARMIN_EFFORT_CATEGORY",
            "message": (
                "The RPE range was mapped to a Garmin effort category and preserved in the "
                "step text."
            ),
        }
    ]
    assert generated.isError is False
    assert generated.structuredContent is not None
    assert generated.structuredContent["data"]["session_count"] == 2
    assert generated.structuredContent["data"]["replayed"] is False
    assert generated_replay.structuredContent is not None
    assert generated_replay.structuredContent["data"]["replayed"] is True
    assert (
        generated_replay.structuredContent["data"]["workout_ids"]
        == generated.structuredContent["data"]["workout_ids"]
    )
    assert stale_apply.isError is True
    assert "PLAN_REVISION_CONFLICT" in stale_apply.content[0].text
    assert tampered_apply.isError is True
    assert "ACTION_TAMPERED" in tampered_apply.content[0].text
    assert loaded_plan.structuredContent is not None
    assert loaded_plan.structuredContent["data"]["notes"][0]["author_type"] == "COACH"
    assert plan_review.structuredContent is not None
    assert plan_review.structuredContent["data"]["eligible"] is True
    assert materialization_proposal.structuredContent is not None
    assert materialization_proposal.structuredContent["data"]["revision_kind"] == "MATERIALIZATION"
    assert materialization_proposal.structuredContent["data"]["decision"] is None
    assert generated_week_two.structuredContent is not None
    assert generated_week_two.structuredContent["data"]["session_count"] == 1
    assert revision_proposal.structuredContent is not None
    assert revision_proposal.structuredContent["data"]["decision"] == "HOLD"
    assert applied_revision.structuredContent is not None
    assert applied_revision.structuredContent["data"]["revision"] == 3
    assert len(applied_revision.structuredContent["data"]["superseded_session_ids"]) == 1
    assert len(applied_revision.structuredContent["data"]["locally_unscheduled_workout_ids"]) == 1
    assert applied_revision.structuredContent["data"]["garmin_changed"] is False
    assert loaded_after_revision.structuredContent is not None
    assert loaded_after_revision.structuredContent["data"]["notes"][0]["text"] == (
        "Consolidar antes de aumentar a carga."
    )
    assert swims.structuredContent is not None
    assert "items" in swims.structuredContent["data"]
    assert missing_swim.isError is True
    error_text = missing_swim.content[0].text
    assert json.loads(error_text[error_text.index("{") :])["schema_version"] == "2.0"
    serialized = (
        str(saved.structuredContent)
        + str(workouts.structuredContent)
        + str(generated.structuredContent)
    )
    assert "action_hash" not in serialized
    assert "content_hash" not in serialized
    assert "proposal" not in serialized.casefold()
    writer = services.garmin_writer
    assert isinstance(writer, FakeGarminWorkoutProvider)
    assert writer.create_calls == 0
    assert writer.update_calls == 0
    assert writer.schedule_calls == 0
    async with database.session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(ActionProposalModel)) == 3
        assert await session.scalar(select(func.count()).select_from(ActionApprovalModel)) == 3
        assert await session.scalar(select(func.count()).select_from(ActionExecutionModel)) == 0
        assert (
            await session.scalar(select(func.count()).select_from(TrainingPlanRevisionModel)) == 3
        )
        stored_reviews = list(await session.scalars(select(PlanReviewModel)))
        assert len(stored_reviews) == 2
        assert all(item.decision is None for item in stored_reviews)
        assert all(item.proposal_id is None for item in stored_reviews)
        binding_states = set(await session.scalars(select(PlanSessionBindingModel.state)))
        assert binding_states == {"SKIPPED", "SUPERSEDED"}
        week_two_workout_id = EntityId.parse(
            generated_week_two.structuredContent["data"]["workout_ids"][0]
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(WorkoutScheduleModel)
                .where(WorkoutScheduleModel.workout_id == week_two_workout_id.value)
            )
            == 0
        )


async def test_direct_save_publish_update_and_reschedule_use_one_binding(
    database: Database, app_settings: Settings
) -> None:
    settings = app_settings.model_copy(
        update={
            "garmin_write_enabled": True,
            "garmin_write_mode": "fake",
            "mcp_write_enabled": True,
            "mcp_v2_enabled": True,
        }
    )
    app = create_app(settings, database)
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
            await client.post("/api/v1/auth/dev-login")
            csrf = client.cookies.get("swim_coach_csrf")
            assert csrf
            me = (await client.get("/api/v1/me")).json()
            pool = (await client.get("/api/v1/pools")).json()[0]
            user_id = UserId.parse(me["user"]["id"])
            now = datetime.now(UTC)
            async with app.state.services.uow_factory() as uow:
                await uow.devices.add(
                    Device(
                        id=EntityId.new(),
                        user_id=user_id,
                        provider="garmin",
                        external_device_id="v2-device",
                        model="Forerunner test",
                        name="Relógio v2",
                        is_primary=True,
                        capabilities={"workout_write": True},
                        last_seen_at=now,
                        created_at=now,
                        updated_at=now,
                    )
                )
                await uow.commit()

            first_date = date.today() + timedelta(days=1)
            definition = canonical_workout()
            nodes = definition["nodes"]
            assert isinstance(nodes, list)
            first_step = nodes[0]
            assert isinstance(first_step, dict)
            first_step["target"] = {"type": "rpe", "min": 5, "max": 6}
            saved = await client.post(
                "/api/v1/workouts/save",
                headers={"X-CSRF-Token": csrf},
                json={
                    "pool_id": pool["id"],
                    "definition": definition,
                    "scheduled_date": first_date.isoformat(),
                    "scheduled_start_time": "19:00:00",
                    "publish_to_garmin": True,
                },
            )
            assert saved.status_code == 200, saved.text
            body = saved.json()
            assert body["workout"]["status"] == "scheduled"
            assert body["garmin"]["status"] == "queued"
            assert body["garmin"]["warnings"] == ["RPE_TARGET_MAPPED_TO_GARMIN_EFFORT_CATEGORY"]
            assert "proposal" not in saved.text.casefold()
            assert "action_hash" not in saved.text
            workout_id = body["workout"]["id"]
            async with database.session_factory() as session:
                payload = await session.scalar(
                    select(JobModel.payload_json).where(
                        JobModel.job_type == "workout.upsert_garmin",
                        JobModel.payload_json["workout_id"].as_string() == workout_id,
                    )
                )
            assert payload is not None
            assert payload["warnings"] == ["RPE_TARGET_MAPPED_TO_GARMIN_EFFORT_CATEGORY"]

            writer = app.state.services.garmin_writer
            assert isinstance(writer, FakeGarminWorkoutProvider)
            worker = Worker(
                app.state.services.uow_factory,
                app.state.services.garmin_sync,
                writer,
                garmin_write_enabled=True,
            )
            assert await worker.run_once()
            assert writer.create_calls == 1
            assert writer.schedule_calls == 1

            replay = await app.state.services.coach_commands.publish_workout(
                user_id,
                EntityId.parse(workout_id),
                scheduled_date=None,
                scheduled_start_time=None,
                device_id=None,
                correlation_id=CorrelationId.new(),
            )
            assert replay.replayed is True
            assert replay.job_id is None
            assert replay.warnings == ("RPE_TARGET_MAPPED_TO_GARMIN_EFFORT_CATEGORY",)

            edited = await client.post(
                "/api/v1/workouts/save",
                headers={"X-CSRF-Token": csrf},
                json={
                    "workout_id": workout_id,
                    "pool_id": pool["id"],
                    "definition": canonical_workout(1_800),
                    "scheduled_date": first_date.isoformat(),
                    "scheduled_start_time": "19:00:00",
                    "publish_to_garmin": True,
                },
            )
            assert edited.status_code == 200, edited.text
            assert await worker.run_once()
            assert writer.create_calls == 1
            assert writer.update_calls == 1
            assert writer.schedule_calls == 1

            second_date = first_date + timedelta(days=1)
            moved = await client.post(
                "/api/v1/workouts/save",
                headers={"X-CSRF-Token": csrf},
                json={
                    "workout_id": workout_id,
                    "pool_id": pool["id"],
                    "definition": canonical_workout(1_800),
                    "scheduled_date": second_date.isoformat(),
                    "scheduled_start_time": "19:00:00",
                    "publish_to_garmin": True,
                },
            )
            assert moved.status_code == 200, moved.text
            assert await worker.run_once()
            assert writer.create_calls == 1
            assert writer.update_calls == 1
            assert writer.unschedule_calls == 1
            assert writer.schedule_calls == 2

    async with database.session_factory() as session:
        assert (
            await session.scalar(select(func.count()).select_from(ExternalWorkoutBindingModel)) == 1
        )
        assert await session.scalar(select(func.count()).select_from(ActionProposalModel)) == 0
        assert await session.scalar(select(func.count()).select_from(ActionApprovalModel)) == 0
        assert await session.scalar(select(func.count()).select_from(ActionExecutionModel)) == 0


async def test_delete_workout_removes_local_schedule_and_garmin_everywhere(
    database: Database, app_settings: Settings
) -> None:
    settings = app_settings.model_copy(
        update={"garmin_write_enabled": True, "garmin_write_mode": "fake"}
    )
    app = create_app(settings, database)
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
            await client.post("/api/v1/auth/dev-login")
            csrf = client.cookies.get("swim_coach_csrf")
            assert csrf
            me = (await client.get("/api/v1/me")).json()
            pool = (await client.get("/api/v1/pools")).json()[0]
            user_id = UserId.parse(me["user"]["id"])
            now = datetime.now(UTC)
            async with app.state.services.uow_factory() as uow:
                await uow.devices.add(
                    Device(
                        id=EntityId.new(),
                        user_id=user_id,
                        provider="garmin",
                        external_device_id="delete-device",
                        model="Forerunner delete test",
                        name="Relógio delete",
                        is_primary=True,
                        capabilities={"workout_write": True},
                        last_seen_at=now,
                        created_at=now,
                        updated_at=now,
                    )
                )
                await uow.commit()

            saved = await client.post(
                "/api/v1/workouts/save",
                headers={"X-CSRF-Token": csrf},
                json={
                    "pool_id": pool["id"],
                    "definition": canonical_workout(),
                    "scheduled_date": (date.today() + timedelta(days=1)).isoformat(),
                    "scheduled_start_time": "19:00:00",
                    "publish_to_garmin": True,
                },
            )
            assert saved.status_code == 200, saved.text
            workout_id = saved.json()["workout"]["id"]
            writer = app.state.services.garmin_writer
            assert isinstance(writer, FakeGarminWorkoutProvider)
            worker = Worker(
                app.state.services.uow_factory,
                app.state.services.garmin_sync,
                writer,
                garmin_write_enabled=True,
                database=database,
            )
            assert await worker.run_once()

            deleted = await client.delete(
                f"/api/v1/workouts/{workout_id}", headers={"X-CSRF-Token": csrf}
            )
            assert deleted.status_code == 202, deleted.text
            assert deleted.json()["local_removed"] is True
            assert deleted.json()["calendar_removed"] is True
            assert deleted.json()["garmin_cleanup"] == "QUEUED"
            assert (await client.get(f"/api/v1/workouts/{workout_id}")).status_code == 404
            assert all(
                item["id"] != workout_id for item in (await client.get("/api/v1/workouts")).json()
            )

            replay = await client.delete(
                f"/api/v1/workouts/{workout_id}", headers={"X-CSRF-Token": csrf}
            )
            assert replay.status_code == 202
            assert replay.json()["replayed"] is True
            assert await worker.run_once()
            assert writer.unschedule_calls == 1
            assert writer.delete_calls == 1

            completed_replay = await client.delete(
                f"/api/v1/workouts/{workout_id}", headers={"X-CSRF-Token": csrf}
            )
            assert completed_replay.status_code == 202
            assert completed_replay.json()["garmin_cleanup"] == "COMPLETED"
            async with app.state.services.uow_factory() as uow:
                assert await uow.workouts.get(user_id, EntityId.parse(workout_id)) is None

            retry_saved = await client.post(
                "/api/v1/workouts/save",
                headers={"X-CSRF-Token": csrf},
                json={
                    "pool_id": pool["id"],
                    "definition": canonical_workout(1_800),
                    "scheduled_date": (date.today() + timedelta(days=2)).isoformat(),
                    "scheduled_start_time": "19:00:00",
                    "publish_to_garmin": True,
                },
            )
            retry_workout_id = retry_saved.json()["workout"]["id"]
            assert await worker.run_once()
            writer.fail_next_delete()
            retry_delete = await client.delete(
                f"/api/v1/workouts/{retry_workout_id}", headers={"X-CSRF-Token": csrf}
            )
            retry_job_id = retry_delete.json()["job_id"]
            assert await worker.run_once()
            async with app.state.services.uow_factory() as uow:
                hidden = await uow.workouts.get(user_id, EntityId.parse(retry_workout_id))
                assert hidden is not None
                assert hidden.status is PlannedWorkoutStatus.DELETING
            async with database.session_factory() as session:
                await session.execute(
                    update(JobModel)
                    .where(JobModel.id == EntityId.parse(retry_job_id).value)
                    .values(available_at=datetime.now(UTC))
                )
                await session.commit()
            assert await worker.run_once()
            async with app.state.services.uow_factory() as uow:
                assert await uow.workouts.get(user_id, EntityId.parse(retry_workout_id)) is None

            completed_saved = await client.post(
                "/api/v1/workouts/save",
                headers={"X-CSRF-Token": csrf},
                json={
                    "pool_id": pool["id"],
                    "definition": canonical_workout(2_000),
                    "scheduled_date": (date.today() + timedelta(days=3)).isoformat(),
                    "scheduled_start_time": "19:00:00",
                    "publish_to_garmin": False,
                },
            )
            completed_id = EntityId.parse(completed_saved.json()["workout"]["id"])
            async with app.state.services.uow_factory() as uow:
                completed = await uow.workouts.get(user_id, completed_id)
                assert completed is not None
                expected_version = completed.version
                completed.status = PlannedWorkoutStatus.COMPLETED
                completed.version += 1
                completed.updated_at = datetime.now(UTC)
                await uow.workouts.update(completed, expected_version=expected_version)
                await uow.commit()
            blocked = await client.delete(
                f"/api/v1/workouts/{completed_id}", headers={"X-CSRF-Token": csrf}
            )
            assert blocked.status_code == 409
            assert blocked.json()["code"] == "WORKOUT_DELETE_COMPLETED_FORBIDDEN"

    async with database.session_factory() as session:
        assert (
            await session.scalar(select(func.count()).select_from(ExternalWorkoutBindingModel)) == 0
        )
        assert await session.scalar(select(func.count()).select_from(ActionProposalModel)) == 0
        assert await session.scalar(select(func.count()).select_from(ActionApprovalModel)) == 0
        assert await session.scalar(select(func.count()).select_from(ActionExecutionModel)) == 0
