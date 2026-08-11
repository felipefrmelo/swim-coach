import httpx
import pytest

from swim_coach.bootstrap.api import create_app


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
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
            response = await client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {"application": "ready"},
    }
