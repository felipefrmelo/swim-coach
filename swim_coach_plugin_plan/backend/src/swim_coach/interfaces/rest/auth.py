"""PWA BFF login, callback, dev login and logout endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response
from fastapi.responses import RedirectResponse

from swim_coach.application.services.sessions import IssuedSession
from swim_coach.domain.shared.errors import DomainError
from swim_coach.interfaces.rest.dependencies import (
    CSRF_COOKIE,
    OIDC_STATE_COOKIE,
    SESSION_COOKIE,
    CsrfAuthenticated,
    RequestCorrelationId,
    Services,
)
from swim_coach.interfaces.rest.schemas import AuthConfigResponse
from swim_coach.settings import Settings

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _settings(request: Request) -> Settings:
    settings = request.app.state.settings
    if not isinstance(settings, Settings):
        raise RuntimeError("application settings are not configured")
    return settings


def _set_session_cookies(response: Response, issued: IssuedSession, settings: Settings) -> None:
    secure = settings.environment == "production"
    response.set_cookie(
        SESSION_COOKIE,
        issued.session_token,
        max_age=settings.session_lifetime_hours * 60 * 60,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE,
        issued.csrf_token,
        max_age=settings.session_lifetime_hours * 60 * 60,
        httponly=False,
        secure=secure,
        samesite="lax",
        path="/",
    )


@router.get("/config", response_model=AuthConfigResponse)
async def auth_config(request: Request) -> AuthConfigResponse:
    settings = _settings(request)
    return AuthConfigResponse(
        oidc_enabled=settings.oidc_issuer is not None,
        dev_auth_enabled=settings.dev_auth_enabled,
    )


@router.get("/login")
async def login(request: Request, services: Services) -> RedirectResponse:
    if services.oidc_login is None:
        raise DomainError("AUTH_REQUIRED", "OIDC login is not configured.")
    started = await services.oidc_login.start()
    settings = _settings(request)
    response = RedirectResponse(started.authorization_url, status_code=303)
    response.set_cookie(
        OIDC_STATE_COOKIE,
        started.state,
        max_age=600,
        httponly=True,
        secure=settings.environment == "production",
        samesite="lax",
        path="/api/v1/auth/callback",
    )
    return response


@router.get("/callback")
async def callback(
    request: Request,
    services: Services,
    correlation_id: RequestCorrelationId,
    code: str,
    state: str,
) -> RedirectResponse:
    if services.oidc_login is None:
        raise DomainError("AUTH_REQUIRED", "OIDC login is not configured.")
    issued = await services.oidc_login.complete(
        state=state,
        state_cookie=request.cookies.get(OIDC_STATE_COOKIE),
        code=code,
        correlation_id=correlation_id,
    )
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie(OIDC_STATE_COOKIE, path="/api/v1/auth/callback")
    _set_session_cookies(response, issued, _settings(request))
    return response


@router.post("/dev-login", status_code=204)
async def dev_login(
    request: Request,
    response: Response,
    services: Services,
    correlation_id: RequestCorrelationId,
) -> None:
    settings = _settings(request)
    if not settings.dev_auth_enabled or settings.environment == "production":
        raise DomainError("AUTH_REQUIRED", "Development authentication is disabled.")
    user = await services.identity.ensure_identity(
        provider="dev",
        subject=f"dev:{settings.dev_auth_email}",
        email=settings.dev_auth_email,
        display_name="Nadador local",
        claims_snapshot={"development": True},
        correlation_id=correlation_id,
    )
    issued = await services.sessions.create(user)
    _set_session_cookies(response, issued, settings)


@router.post("/logout", status_code=204)
async def logout(
    response: Response,
    authenticated: CsrfAuthenticated,
    services: Services,
    correlation_id: RequestCorrelationId,
) -> None:
    await services.sessions.revoke(authenticated, correlation_id=correlation_id)
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
