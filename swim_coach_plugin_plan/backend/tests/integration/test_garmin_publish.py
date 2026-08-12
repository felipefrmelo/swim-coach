"""P07 REST approval, worker idempotency and ambiguous-result reconciliation."""

from datetime import UTC, date, datetime

import httpx

from swim_coach.bootstrap.api import create_app
from swim_coach.domain.athlete import Device
from swim_coach.domain.shared.value_objects import EntityId, UserId
from swim_coach.infrastructure.db import Database
from swim_coach.infrastructure.garmin import FakeGarminWorkoutProvider
from swim_coach.interfaces.worker.main import Worker
from swim_coach.settings import Settings


def canonical_workout() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "title": "Endurance descartável — 1.600 m",
        "sport": "POOL_SWIMMING",
        "pool_length_m": 20,
        "purpose": "ENDURANCE",
        "tags": ["canary", "20m"],
        "nodes": [
            {
                "type": "step",
                "step_role": "WARMUP",
                "end_condition": {"type": "distance", "meters": 200},
            },
            {
                "type": "repeat",
                "repetitions": 6,
                "children": [
                    {
                        "type": "step",
                        "step_role": "WORK",
                        "end_condition": {"type": "distance", "meters": 200},
                    },
                    {
                        "type": "step",
                        "step_role": "REST",
                        "end_condition": {"type": "time", "seconds": 20},
                    },
                ],
            },
            {
                "type": "step",
                "step_role": "COOLDOWN",
                "end_condition": {"type": "distance", "meters": 200},
            },
        ],
    }


async def test_proposal_approval_ambiguous_reconciliation_and_replay(
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
            user_id = UserId.parse(me["user"]["id"])
            pool = (await client.get("/api/v1/pools")).json()[0]
            now = datetime.now(UTC)
            async with app.state.services.uow_factory() as uow:
                await uow.devices.add(
                    Device(
                        id=EntityId.new(),
                        user_id=user_id,
                        provider="garmin",
                        external_device_id="fake-device-1",
                        model="Forerunner test",
                        name="Relógio descartável",
                        is_primary=True,
                        capabilities={"workout_write": True},
                        last_seen_at=now,
                        created_at=now,
                        updated_at=now,
                    )
                )
                await uow.commit()
            created = await client.post(
                "/api/v1/workouts",
                headers={"X-CSRF-Token": csrf},
                json={"pool_id": pool["id"], "definition": canonical_workout()},
            )
            workout = created.json()
            approved = await client.post(
                f"/api/v1/workouts/{workout['id']}/approve-local",
                headers={"X-CSRF-Token": csrf, "If-Match": created.headers["etag"]},
                json={"content_hash": workout["current_revision"]["content_hash"]},
            )
            scheduled = await client.post(
                f"/api/v1/workouts/{workout['id']}/schedule",
                headers={"X-CSRF-Token": csrf, "If-Match": approved.headers["etag"]},
                json={
                    "scheduled_date": date.today().isoformat(),
                    "scheduled_start_time": "19:00:00",
                    "timezone": "America/Sao_Paulo",
                    "pool_id": pool["id"],
                },
            )
            preview = await client.post(
                f"/api/v1/workouts/{workout['id']}/garmin-proposals",
                headers={"X-CSRF-Token": csrf, "If-Match": scheduled.headers["etag"]},
                json={"device_id": None},
            )
            assert preview.status_code == 201, preview.text
            proposal = preview.json()
            assert proposal["status"] == "READY_FOR_REVIEW"
            assert proposal["impact"]["distance_m"] == 1_600
            assert proposal["impact"]["external_effects"] == [
                "create Garmin workout",
                "add to Garmin calendar",
            ]
            approval = await client.post(
                f"/api/v1/actions/{proposal['id']}/approve",
                headers={"X-CSRF-Token": csrf, "If-Match": preview.headers["etag"]},
                json={"action_hash": proposal["action_hash"]},
            )
            assert approval.status_code == 200, approval.text
            assert approval.json()["status"] == "QUEUED"
            replay = await client.post(
                f"/api/v1/actions/{proposal['id']}/approve",
                headers={"X-CSRF-Token": csrf, "If-Match": preview.headers["etag"]},
                json={"action_hash": proposal["action_hash"]},
            )
            assert replay.status_code == 200
            assert replay.json()["execution"]["id"] == approval.json()["execution"]["id"]

            provider = FakeGarminWorkoutProvider(
                ambiguous_create_once=True, ambiguous_schedule_once=True
            )
            worker = Worker(
                app.state.services.uow_factory,
                app.state.services.garmin_sync,
                provider,
                garmin_write_enabled=True,
                worker_id="worker-p07-test",
            )
            assert await worker.run_once() is True
            assert await worker.run_once() is True
            assert await worker.run_once() is False
            result = await client.get(f"/api/v1/actions/{proposal['id']}")
            assert result.status_code == 200
            assert result.json()["status"] == "SUCCEEDED"
            assert result.json()["execution"]["status"] == "SUCCEEDED"
            assert provider.create_calls == 1
            assert provider.schedule_calls == 1
