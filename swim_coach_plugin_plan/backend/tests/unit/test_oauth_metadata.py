import httpx
import pytest
from pydantic import ValidationError

from swim_coach.application.services.mcp_read import MCP_READ_SCOPES
from swim_coach.application.services.mcp_write import MCP_WRITE_SCOPES
from swim_coach.bootstrap.api import create_app
from swim_coach.settings import Settings, get_settings


@pytest.fixture(autouse=True)
def clear_settings_cache() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_protected_resource_metadata_is_hidden_when_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SWIM_COACH_OAUTH_ISSUER", raising=False)
    monkeypatch.delenv("SWIM_COACH_OAUTH_RESOURCE", raising=False)
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
            response = await client.get("/.well-known/oauth-protected-resource")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_protected_resource_metadata_uses_configured_https_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SWIM_COACH_OAUTH_ISSUER", "https://tenant.example.com/")
    monkeypatch.setenv("SWIM_COACH_OAUTH_RESOURCE", "https://swim.example.com/mcp/")
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
            root_response = await client.get("/.well-known/oauth-protected-resource")
            path_response = await client.get("/.well-known/oauth-protected-resource/mcp")

    expected = {
        "resource": "https://swim.example.com/mcp",
        "authorization_servers": ["https://tenant.example.com"],
        "scopes_supported": list(MCP_READ_SCOPES),
    }
    assert root_response.status_code == 200
    assert root_response.json() == expected
    assert path_response.status_code == 200
    assert path_response.json() == expected


@pytest.mark.asyncio
async def test_protected_resource_advertises_write_scopes_only_with_kill_switch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SWIM_COACH_OAUTH_ISSUER", "https://tenant.example.com/")
    monkeypatch.setenv("SWIM_COACH_OAUTH_RESOURCE", "https://swim.example.com/mcp/")
    monkeypatch.setenv("SWIM_COACH_MCP_WRITE_ENABLED", "true")
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
            response = await client.get("/.well-known/oauth-protected-resource")

    assert response.status_code == 200
    assert response.json()["scopes_supported"] == list((*MCP_READ_SCOPES, *MCP_WRITE_SCOPES))


def test_oauth_resource_allows_development_loopback_http() -> None:
    settings = Settings(
        _env_file=None,
        environment="development",
        oauth_issuer="https://tenant.example.com",
        oauth_resource="http://127.0.0.1:18000/mcp/",
    )

    assert str(settings.oauth_resource).rstrip("/") == "http://127.0.0.1:18000/mcp"


@pytest.mark.parametrize(
    ("issuer", "resource"),
    [
        ("https://tenant.example.com", None),
        (None, "https://swim.example.com/mcp"),
        ("http://tenant.example.com", "https://swim.example.com/mcp"),
        ("https://tenant.example.com", "http://192.0.2.1/mcp"),
    ],
)
def test_oauth_metadata_settings_require_complete_https_pair(
    issuer: str | None,
    resource: str | None,
) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, oauth_issuer=issuer, oauth_resource=resource)


def test_oauth_resource_rejects_loopback_http_in_production() -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            environment="production",
            oauth_issuer="https://tenant.example.com",
            oauth_resource="http://127.0.0.1:18000/mcp/",
        )
