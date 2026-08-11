"""User account and external identity entities."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from swim_coach.domain.shared.errors import DomainValidationError
from swim_coach.domain.shared.types import JsonObject
from swim_coach.domain.shared.value_objects import EntityId, UserId


def utc_now() -> datetime:
    return datetime.now(UTC)


class UserStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"
    DELETED = "deleted"


@dataclass(slots=True)
class AppUser:
    id: UserId
    email: str
    display_name: str
    locale: str = "pt-BR"
    timezone: str = "America/Sao_Paulo"
    status: UserStatus = UserStatus.ACTIVE
    last_login_at: datetime | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    version: int = 1

    def __post_init__(self) -> None:
        self.email = self.email.strip().casefold()
        self.display_name = self.display_name.strip()
        if "@" not in self.email or not self.display_name:
            raise DomainValidationError("user email and display name are required")
        if not self.locale or "/" not in self.timezone:
            raise DomainValidationError("locale and IANA timezone are required")
        if self.version < 1:
            raise DomainValidationError("user version must start at one")


@dataclass(slots=True)
class AuthIdentity:
    id: EntityId
    user_id: UserId
    provider: str
    subject: str
    claims_snapshot: JsonObject = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        self.provider = self.provider.strip().casefold()
        self.subject = self.subject.strip()
        if not self.provider or not self.subject:
            raise DomainValidationError("identity provider and subject are required")


@dataclass(slots=True)
class WebSession:
    """Revocable browser session; only hashes of bearer material are persisted."""

    id: EntityId
    user_id: UserId
    token_hash: str
    csrf_hash: str
    expires_at: datetime
    created_at: datetime = field(default_factory=utc_now)
    last_seen_at: datetime = field(default_factory=utc_now)
    revoked_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.token_hash or not self.csrf_hash or self.created_at >= self.expires_at:
            raise DomainValidationError("web session hashes and a future expiry are required")


@dataclass(slots=True)
class OidcLoginAttempt:
    """Short-lived server-side PKCE and nonce state."""

    id: EntityId
    state_hash: str
    code_verifier: str
    nonce: str
    redirect_uri: str
    expires_at: datetime
    created_at: datetime = field(default_factory=utc_now)
    consumed_at: datetime | None = None

    def __post_init__(self) -> None:
        if not all((self.state_hash, self.code_verifier, self.nonce, self.redirect_uri)):
            raise DomainValidationError("complete OIDC login state is required")
        if self.created_at >= self.expires_at:
            raise DomainValidationError("OIDC login state expiry must be in the future")
