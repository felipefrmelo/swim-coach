"""Opaque BFF browser-session lifecycle."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from swim_coach.application.ports.repositories import UnitOfWorkFactory
from swim_coach.domain.identity import AppUser, WebSession
from swim_coach.domain.operations import AuditEvent
from swim_coach.domain.shared.errors import DomainError
from swim_coach.domain.shared.value_objects import CorrelationId, EntityId


def hash_bearer(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class IssuedSession:
    session_token: str
    csrf_token: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class AuthenticatedSession:
    session: WebSession
    user: AppUser


class SessionService:
    def __init__(self, uow_factory: UnitOfWorkFactory, *, lifetime: timedelta) -> None:
        self._uow_factory = uow_factory
        self._lifetime = lifetime

    async def create(self, user: AppUser) -> IssuedSession:
        now = datetime.now(UTC)
        session_token = secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(32)
        expires_at = now + self._lifetime
        session = WebSession(
            id=EntityId.new(),
            user_id=user.id,
            token_hash=hash_bearer(session_token),
            csrf_hash=hash_bearer(csrf_token),
            expires_at=expires_at,
            created_at=now,
            last_seen_at=now,
        )
        async with self._uow_factory() as uow:
            await uow.sessions.add(session)
            await uow.commit()
        return IssuedSession(session_token, csrf_token, expires_at)

    async def authenticate(self, session_token: str | None) -> AuthenticatedSession:
        if not session_token:
            raise DomainError("AUTH_REQUIRED", "Authentication is required.")
        now = datetime.now(UTC)
        async with self._uow_factory() as uow:
            session = await uow.sessions.get_active_by_token_hash(hash_bearer(session_token), now)
            if session is None:
                raise DomainError("AUTH_REQUIRED", "Authentication is required.")
            user = await uow.users.get(session.user_id)
            if user is None or user.status.value != "active":
                raise DomainError("ACCOUNT_DISABLED", "This account is not active.")
            return AuthenticatedSession(session=session, user=user)

    async def require_csrf(
        self,
        authenticated: AuthenticatedSession,
        *,
        csrf_cookie: str | None,
        csrf_header: str | None,
    ) -> None:
        if (
            not csrf_cookie
            or not csrf_header
            or not secrets.compare_digest(csrf_cookie, csrf_header)
            or not secrets.compare_digest(authenticated.session.csrf_hash, hash_bearer(csrf_header))
        ):
            raise DomainError("TOKEN_INVALID", "The CSRF token is missing or invalid.")

    async def revoke(
        self,
        authenticated: AuthenticatedSession,
        *,
        correlation_id: CorrelationId,
    ) -> None:
        now = datetime.now(UTC)
        async with self._uow_factory() as uow:
            await uow.sessions.revoke(authenticated.session.id, now)
            await uow.audit.add(
                AuditEvent(
                    id=EntityId.new(),
                    user_id=authenticated.user.id,
                    actor_type="user",
                    actor_id=str(authenticated.user.id),
                    action="identity.logout",
                    entity_type="WebSession",
                    entity_id=authenticated.session.id,
                    correlation_id=correlation_id,
                )
            )
            await uow.commit()
