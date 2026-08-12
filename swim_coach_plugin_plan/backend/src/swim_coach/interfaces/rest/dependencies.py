"""FastAPI dependencies for P01 user-scoped requests."""

from __future__ import annotations

from typing import Annotated

from fastapi import Cookie, Depends, Header, Request

from swim_coach.application.services.sessions import AuthenticatedSession
from swim_coach.bootstrap.container import AppServices
from swim_coach.domain.shared.value_objects import CorrelationId

SESSION_COOKIE = "swim_coach_session"
CSRF_COOKIE = "swim_coach_csrf"
OIDC_STATE_COOKIE = "swim_coach_oidc_state"


def get_services(request: Request) -> AppServices:
    services = request.app.state.services
    if not isinstance(services, AppServices):
        raise RuntimeError("application services are not configured")
    return services


def get_correlation_id(request: Request) -> CorrelationId:
    value = request.state.correlation_id
    if not isinstance(value, CorrelationId):
        raise RuntimeError("correlation id middleware is not installed")
    return value


async def get_authenticated_session(
    services: Annotated[AppServices, Depends(get_services)],
    session_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> AuthenticatedSession:
    return await services.sessions.authenticate(session_token)


async def get_csrf_session(
    authenticated: Annotated[AuthenticatedSession, Depends(get_authenticated_session)],
    services: Annotated[AppServices, Depends(get_services)],
    csrf_cookie: Annotated[str | None, Cookie(alias=CSRF_COOKIE)] = None,
    csrf_header: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> AuthenticatedSession:
    await services.sessions.require_csrf(
        authenticated,
        csrf_cookie=csrf_cookie,
        csrf_header=csrf_header,
    )
    return authenticated


Authenticated = Annotated[AuthenticatedSession, Depends(get_authenticated_session)]
CsrfAuthenticated = Annotated[AuthenticatedSession, Depends(get_csrf_session)]
Services = Annotated[AppServices, Depends(get_services)]
RequestCorrelationId = Annotated[CorrelationId, Depends(get_correlation_id)]
