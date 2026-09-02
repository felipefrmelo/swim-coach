from unittest.mock import AsyncMock

import httpx
import pytest

from swim_coach.bootstrap.api import create_app
from swim_coach.settings import Settings


@pytest.mark.asyncio
async def test_liveness() -> None:
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
            response = await client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "swim-coach-api"}


@pytest.mark.asyncio
async def test_readiness() -> None:
    app = create_app()
    app.state.services.database.ping = AsyncMock(return_value=True)
    app.state.services.database.revision = AsyncMock(return_value="000014")
    app.state.services.artifact_storage.readiness = AsyncMock(return_value=True)
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
            response = await client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {
            "application": "ready",
            "database": "ready",
            "schema": "000014",
            "artifact_storage": "ready",
        },
    }


@pytest.mark.asyncio
async def test_rest_security_headers_and_rate_limit(tmp_path) -> None:
    settings = Settings(
        _env_file=None,
        environment="test",
        api_read_rate_limit_per_minute=1,
        activity_storage_path=tmp_path,
    )
    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
            first = await client.get("/api/v1/auth/config")
            limited = await client.get("/api/v1/auth/config")

    assert first.status_code == 200
    assert first.headers["cache-control"] == "no-store"
    assert first.headers["content-security-policy"].startswith("default-src 'none'")
    assert limited.status_code == 429
    assert limited.json()["code"] == "RATE_LIMITED"
