"""ASGI composition root."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from fastapi import FastAPI

from swim_coach import __version__
from swim_coach.bootstrap.container import build_services
from swim_coach.infrastructure.db import Database
from swim_coach.interfaces.mcp.server import create_mcp_server
from swim_coach.interfaces.rest.actions import router as actions_router
from swim_coach.interfaces.rest.auth import router as auth_router
from swim_coach.interfaces.rest.context import router as context_router
from swim_coach.interfaces.rest.garmin import router as garmin_router
from swim_coach.interfaces.rest.health import router as health_router
from swim_coach.interfaces.rest.oauth import router as oauth_router
from swim_coach.interfaces.rest.problem import install_problem_handlers
from swim_coach.interfaces.rest.workouts import router as workouts_router
from swim_coach.settings import Settings, get_settings


def create_app(
    settings_override: Settings | None = None,
    database_override: Database | None = None,
) -> FastAPI:
    """Build REST, P00 MCP and the P01 transactional services."""

    settings = settings_override or get_settings()
    services = build_services(settings, database_override)
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
            try:
                yield
            finally:
                await services.database.dispose()

    app = FastAPI(
        title="Swim Coach",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.services = services
    install_problem_handlers(app)
    app.include_router(health_router)
    app.include_router(oauth_router)
    app.include_router(auth_router)
    app.include_router(context_router)
    app.include_router(garmin_router)
    app.include_router(workouts_router)
    app.include_router(actions_router)
    app.mount("/mcp", mcp_app)
    return app


app = create_app()
