"""OIDC login orchestration without persisting provider tokens."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from secrets import compare_digest

from swim_coach.application.ports.repositories import UnitOfWorkFactory
from swim_coach.application.services.identity import IdentityService
from swim_coach.application.services.sessions import IssuedSession, SessionService, hash_bearer
from swim_coach.domain.identity import OidcLoginAttempt
from swim_coach.domain.shared.errors import DomainError
from swim_coach.domain.shared.value_objects import CorrelationId, EntityId
from swim_coach.infrastructure.auth import OidcClient


@dataclass(frozen=True, slots=True)
class StartedLogin:
    authorization_url: str
    state: str


class OidcLoginService:
    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory,
        oidc_client: OidcClient,
        identity_service: IdentityService,
        session_service: SessionService,
        redirect_uri: str,
    ) -> None:
        self._uow_factory = uow_factory
        self._oidc_client = oidc_client
        self._identity_service = identity_service
        self._session_service = session_service
        self._redirect_uri = redirect_uri

    async def start(self) -> StartedLogin:
        authorization = await self._oidc_client.begin_authorization(self._redirect_uri)
        attempt = OidcLoginAttempt(
            id=EntityId.new(),
            state_hash=hash_bearer(authorization.state),
            code_verifier=authorization.code_verifier,
            nonce=authorization.nonce,
            redirect_uri=self._redirect_uri,
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
        )
        async with self._uow_factory() as uow:
            await uow.oidc_login_attempts.add(attempt)
            await uow.commit()
        return StartedLogin(authorization.url, authorization.state)

    async def complete(
        self,
        *,
        state: str,
        state_cookie: str | None,
        code: str,
        correlation_id: CorrelationId,
    ) -> IssuedSession:
        if not state_cookie or not compare_digest(state, state_cookie):
            raise DomainError("TOKEN_INVALID", "OIDC state did not match the browser session.")
        now = datetime.now(UTC)
        async with self._uow_factory() as uow:
            attempt = await uow.oidc_login_attempts.consume(hash_bearer(state), now)
            if attempt is None:
                raise DomainError("TOKEN_INVALID", "OIDC login state is invalid or expired.")
            await uow.commit()
        principal = await self._oidc_client.exchange_code(
            code=code,
            code_verifier=attempt.code_verifier,
            nonce=attempt.nonce,
            redirect_uri=attempt.redirect_uri,
        )
        user = await self._identity_service.ensure_identity(
            provider="oidc",
            subject=principal.subject,
            email=principal.email,
            display_name=principal.display_name,
            claims_snapshot=dict(principal.claims_snapshot),
            correlation_id=correlation_id,
        )
        return await self._session_service.create(user)
