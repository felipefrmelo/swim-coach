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
)
from swim_coach.infrastructure.garmin import FakeGarminWorkoutProvider
from swim_coach.interfaces.mcp.server import create_mcp_server
from swim_coach.interfaces.worker.main import Worker
from swim_coach.settings import Settings

from .test_workout_authoring import canonical_workout


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
            AvailabilityInput(0, time(7), time(8), 60, pools[0].id),
            AvailabilityInput(2, time(7), time(8), 60, pools[0].id),
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
                        "get_workouts",
                        "get_swims",
                        "save_workout",
                        "publish_workout",
                        "delete_workout",
                        "generate_week",
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
                    generated = await session.call_tool(
                        "generate_week",
                        {
                            "week_start": next_monday.isoformat(),
                            "session_count": 2,
                            "focus": "BALANCED",
                        },
                    )

    assert saved.isError is False
    assert saved.structuredContent is not None
    assert all(
        result.structuredContent is not None and result.structuredContent["schema_version"] == "2.0"
        for result in (saved, published, workouts, swims, generated)
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
    async with database.session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(ActionProposalModel)) == 0
        assert await session.scalar(select(func.count()).select_from(ActionApprovalModel)) == 0
        assert await session.scalar(select(func.count()).select_from(ActionExecutionModel)) == 0


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
