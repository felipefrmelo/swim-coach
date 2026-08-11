"""ASGI composition root."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from fastapi import FastAPI

from swim_coach import __version__
from swim_coach.interfaces.mcp.server import create_mcp_server
from swim_coach.interfaces.rest.health import router as health_router
from swim_coach.interfaces.rest.oauth import router as oauth_router
from swim_coach.settings import get_settings


def create_app() -> FastAPI:
    """Build the API, including the harmless P00 MCP endpoint."""

    settings = get_settings()
    allowed_hosts: list[str] | None = None
    allowed_origins: list[str] | None = None
    if settings.public_base_url is not None:
        public_url = str(settings.public_base_url).rstrip("/")
        parsed = urlparse(public_url)
        allowed_hosts = [parsed.netloc]
        allowed_origins = [public_url]
    mcp_server = create_mcp_server(
        allowed_hosts=allowed_hosts,
        allowed_origins=allowed_origins,
    )
    mcp_app = mcp_server.streamable_http_app()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        async with mcp_server.session_manager.run():
            yield

    app = FastAPI(
        title="Swim Coach",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.include_router(health_router)
    app.include_router(oauth_router)
    app.mount("/mcp", mcp_app)
    return app


app = create_app()
