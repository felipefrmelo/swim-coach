from datetime import date

import httpx

from swim_coach.bootstrap.api import create_app
from swim_coach.infrastructure.db import Database
from swim_coach.settings import Settings


def canonical_workout(distance_m: int = 1_600) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "title": f"Endurance controlado — {distance_m} m",
        "sport": "POOL_SWIMMING",
        "pool_length_m": 20,
        "purpose": "ENDURANCE",
        "tags": ["endurance", "20m"],
        "nodes": [
            {
                "type": "step",
                "id": "warmup",
                "step_role": "WARMUP",
                "end_condition": {"type": "distance", "meters": 200},
                "intensity": "EASY",
            },
            {
                "type": "repeat",
                "id": "main",
                "repetitions": 6,
                "children": [
                    {
                        "type": "step",
                        "step_role": "WORK",
                        "end_condition": {"type": "distance", "meters": 200},
                        "target": {
                            "type": "pace_range",
                            "min_seconds_per_100m": 140,
                            "max_seconds_per_100m": 150,
                        },
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
                "id": "cooldown",
                "step_role": "COOLDOWN",
                "end_condition": {"type": "distance", "meters": distance_m - 1_400},
                "intensity": "EASY",
            },
        ],
    }


async def test_create_revise_approve_schedule_and_revision_conflict(
    database: Database, app_settings: Settings
) -> None:
    app = create_app(app_settings, database)
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        assert not hasattr(app.state.services.workouts, "_garmin")
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
            await client.post("/api/v1/auth/dev-login")
            csrf = client.cookies.get("swim_coach_csrf")
            assert csrf
            pool = (await client.get("/api/v1/pools")).json()[0]
            create = await client.post(
                "/api/v1/workouts",
                headers={"X-CSRF-Token": csrf},
                json={"pool_id": pool["id"], "definition": canonical_workout()},
            )
            assert create.status_code == 201, create.text
            assert create.json()["current_revision"]["validation"]["totals"]["distance_m"] == 1_600
            assert create.headers["etag"] == '"2"'
            workout_id = create.json()["id"]

            changed = canonical_workout(1_800)
            revise = await client.post(
                f"/api/v1/workouts/{workout_id}/revisions",
                headers={"X-CSRF-Token": csrf, "If-Match": '"2"'},
                json={"definition": changed, "change_reason": "Mais soltura"},
            )
            assert revise.status_code == 200, revise.text
            assert revise.json()["current_revision"]["revision_number"] == 2
            assert len(revise.json()["revisions"]) == 2

            stale = await client.post(
                f"/api/v1/workouts/{workout_id}/revisions",
                headers={"X-CSRF-Token": csrf, "If-Match": '"2"'},
                json={"definition": changed},
            )
            assert stale.status_code == 409
            assert stale.json()["code"] == "REVISION_CONFLICT"

            current = revise.json()["current_revision"]
            approve = await client.post(
                f"/api/v1/workouts/{workout_id}/approve-local",
                headers={"X-CSRF-Token": csrf, "If-Match": revise.headers["etag"]},
                json={"content_hash": current["content_hash"]},
            )
            assert approve.status_code == 200, approve.text
            assert approve.json()["status"] == "approved"

            schedule = await client.post(
                f"/api/v1/workouts/{workout_id}/schedule",
                headers={"X-CSRF-Token": csrf, "If-Match": approve.headers["etag"]},
                json={
                    "scheduled_date": str(date.today()),
                    "scheduled_start_time": "19:00:00",
                    "timezone": "America/Sao_Paulo",
                    "pool_id": pool["id"],
                },
            )
            assert schedule.status_code == 200, schedule.text
            assert schedule.json()["status"] == "scheduled"
            assert schedule.json()["schedule"]["timezone"] == "America/Sao_Paulo"


async def test_invalid_distance_can_be_saved_as_draft_but_not_approved(
    database: Database, app_settings: Settings
) -> None:
    app = create_app(app_settings, database)
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
            await client.post("/api/v1/auth/dev-login")
            csrf = client.cookies.get("swim_coach_csrf")
            pool = (await client.get("/api/v1/pools")).json()[0]
            payload = canonical_workout(1_610)
            created = await client.post(
                "/api/v1/workouts",
                headers={"X-CSRF-Token": csrf},
                json={"pool_id": pool["id"], "definition": payload},
            )
            assert created.status_code == 201
            assert not created.json()["current_revision"]["validation"]["valid"]
            approval = await client.post(
                f"/api/v1/workouts/{created.json()['id']}/approve-local",
                headers={"X-CSRF-Token": csrf, "If-Match": created.headers["etag"]},
                json={"content_hash": created.json()["current_revision"]["content_hash"]},
            )
            assert approval.status_code == 422
            assert approval.json()["code"] == "VALIDATION_FAILED"
