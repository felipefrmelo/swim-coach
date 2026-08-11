import httpx

from swim_coach.bootstrap.api import create_app
from swim_coach.domain.shared import CorrelationId
from swim_coach.infrastructure.db import Database
from swim_coach.settings import Settings


async def test_authenticated_context_csrf_logout_and_problem_details(
    database: Database,
    app_settings: Settings,
) -> None:
    app = create_app(app_settings, database)
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
            anonymous = await client.get("/api/v1/me")
            assert anonymous.status_code == 401
            assert anonymous.headers["content-type"].startswith("application/problem+json")
            assert anonymous.json()["code"] == "AUTH_REQUIRED"
            assert anonymous.json()["correlation_id"] == anonymous.headers["x-correlation-id"]

            login = await client.post("/api/v1/auth/dev-login")
            assert login.status_code == 204
            me = await client.get("/api/v1/me")
            assert me.status_code == 200
            assert me.json()["profile"]["default_sessions_per_week"] == 3
            csrf = client.cookies.get("swim_coach_csrf")
            assert csrf

            rejected = await client.patch(
                "/api/v1/me/profile",
                json={
                    "display_name": "Atualizado",
                    "locale": "pt-BR",
                    "timezone": "America/Sao_Paulo",
                    "experience_level": "intermediate",
                    "default_sessions_per_week": 4,
                    "version": me.json()["profile"]["version"],
                },
            )
            assert rejected.status_code == 403
            updated = await client.patch(
                "/api/v1/me/profile",
                headers={"X-CSRF-Token": csrf},
                json={
                    "display_name": "Atualizado",
                    "locale": "pt-BR",
                    "timezone": "America/Sao_Paulo",
                    "experience_level": "intermediate",
                    "default_sessions_per_week": 4,
                    "version": me.json()["profile"]["version"],
                },
            )
            assert updated.status_code == 200
            assert updated.json()["profile"]["default_sessions_per_week"] == 4

            pool_payload = {
                "name": "Piscina idempotente",
                "length_m": 25,
                "is_default": False,
                "location_label": None,
            }
            first_pool = await client.post(
                "/api/v1/pools",
                headers={"X-CSRF-Token": csrf, "Idempotency-Key": "pool-create-001"},
                json=pool_payload,
            )
            replayed_pool = await client.post(
                "/api/v1/pools",
                headers={"X-CSRF-Token": csrf, "Idempotency-Key": "pool-create-001"},
                json=pool_payload,
            )
            assert first_pool.status_code == 201
            assert replayed_pool.json()["id"] == first_pool.json()["id"]
            conflict = await client.post(
                "/api/v1/pools",
                headers={"X-CSRF-Token": csrf, "Idempotency-Key": "pool-create-001"},
                json={**pool_payload, "length_m": 50},
            )
            assert conflict.status_code == 409
            assert conflict.json()["code"] == "IDEMPOTENCY_CONFLICT"

            logout = await client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})
            assert logout.status_code == 204
            assert (await client.get("/api/v1/me")).status_code == 401


async def test_endpoint_hides_other_users_resources_as_not_found(
    database: Database,
    app_settings: Settings,
) -> None:
    app = create_app(app_settings, database)
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        services = app.state.services
        second = await services.identity.ensure_identity(
            provider="test",
            subject="second-subject",
            email="second@example.test",
            display_name="Segundo",
            claims_snapshot={"email_verified": True},
            correlation_id=CorrelationId.new(),
        )
        second_pools = await services.context.list_pools(second.id)
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
            await client.post("/api/v1/auth/dev-login")
            csrf = client.cookies.get("swim_coach_csrf")
            assert csrf
            response = await client.patch(
                f"/api/v1/pools/{second_pools[0].id}",
                headers={"X-CSRF-Token": csrf},
                json={
                    "name": "Tentativa cruzada",
                    "length_m": 25,
                    "is_default": False,
                    "active": True,
                    "location_label": None,
                    "version": second_pools[0].version,
                },
            )

    assert response.status_code == 404
    assert response.json()["code"] == "RESOURCE_NOT_FOUND"
    unchanged = await services.context.list_pools(second.id)
    assert unchanged[0].name == "Piscina principal"
