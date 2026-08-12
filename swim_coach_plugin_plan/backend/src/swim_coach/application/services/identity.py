"""User-scoped identity bootstrap and allowlist policy."""

from __future__ import annotations

from datetime import UTC, datetime

from swim_coach.application.ports.repositories import UnitOfWork, UnitOfWorkFactory
from swim_coach.domain.athlete import AthleteProfile, Pool
from swim_coach.domain.goals import TrainingGoal
from swim_coach.domain.identity import AppUser, AuthIdentity, UserStatus
from swim_coach.domain.operations import AuditEvent, OutboxEvent
from swim_coach.domain.shared.errors import DomainError
from swim_coach.domain.shared.types import JsonObject
from swim_coach.domain.shared.value_objects import (
    CorrelationId,
    EntityId,
    PoolLength,
    UserId,
)


class IdentityService:
    """Maps an allowlisted OIDC/dev principal to a local user transactionally."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        *,
        allowed_emails: frozenset[str],
        allowed_subjects: frozenset[str],
    ) -> None:
        self._uow_factory = uow_factory
        self._allowed_emails = frozenset(item.casefold() for item in allowed_emails)
        self._allowed_subjects = allowed_subjects

    def _is_allowed(self, email: str, subject: str) -> bool:
        return email.casefold() in self._allowed_emails or subject in self._allowed_subjects

    async def resolve_identity(self, *, provider: str, subject: str) -> AppUser:
        """Resolve an existing active identity without creating or updating state."""

        async with self._uow_factory() as uow:
            identity = await uow.identities.get(provider, subject)
            if identity is None:
                raise DomainError("ACCOUNT_DISABLED", "This identity is not linked.")
            user = await uow.users.get(identity.user_id)
            if user is None or user.status is not UserStatus.ACTIVE:
                raise DomainError("ACCOUNT_DISABLED", "This account is not active.")
            if not self._is_allowed(user.email, subject):
                raise DomainError("ACCOUNT_DISABLED", "This identity is not allowed.")
            return user

    async def ensure_identity(
        self,
        *,
        provider: str,
        subject: str,
        email: str,
        display_name: str,
        claims_snapshot: JsonObject,
        correlation_id: CorrelationId,
    ) -> AppUser:
        email = email.strip().casefold()
        if not self._is_allowed(email, subject):
            raise DomainError("ACCOUNT_DISABLED", "This identity is not allowed to use Swim Coach.")

        now = datetime.now(UTC)
        async with self._uow_factory() as uow:
            identity = await uow.identities.get(provider, subject)
            if identity is not None:
                user = await uow.users.get(identity.user_id)
                if user is None or user.status is not UserStatus.ACTIVE:
                    raise DomainError("ACCOUNT_DISABLED", "This account is not active.")
                previous_version = user.version
                user.last_login_at = now
                user.updated_at = now
                user.version += 1
                await uow.users.update(user, expected_version=previous_version)
                await self._audit_login(uow, user, provider, correlation_id)
                await uow.commit()
                return user

            user = await uow.users.get_by_email(email)
            if user is None:
                user = AppUser(
                    id=UserId.new(),
                    email=email,
                    display_name=display_name,
                    last_login_at=now,
                )
                default_pool = Pool(
                    id=EntityId.new(),
                    user_id=user.id,
                    name="Piscina principal",
                    length=PoolLength(20),
                    is_default=True,
                )
                profile = AthleteProfile(user_id=user.id, default_pool_id=default_pool.id)
                goal = TrainingGoal.initial_two_k(user.id)
                await uow.users.add(user)
                await uow.flush()
                await uow.pools.add(default_pool)
                await uow.flush()
                await uow.profiles.add(profile)
                await uow.goals.add(goal)
                await uow.outbox.add(
                    OutboxEvent(
                        id=EntityId.new(),
                        aggregate_type="TrainingGoal",
                        aggregate_id=goal.id,
                        event_type="swim_coach.goals.goal_activated.v1",
                        payload={"goal_id": str(goal.id)},
                        user_id=user.id,
                        correlation_id=correlation_id,
                    )
                )
            elif user.status is not UserStatus.ACTIVE:
                raise DomainError("ACCOUNT_DISABLED", "This account is not active.")

            await uow.identities.add(
                AuthIdentity(
                    id=EntityId.new(),
                    user_id=user.id,
                    provider=provider,
                    subject=subject,
                    claims_snapshot=claims_snapshot,
                )
            )
            await self._audit_login(uow, user, provider, correlation_id)
            await uow.commit()
            return user

    @staticmethod
    async def _audit_login(
        uow: UnitOfWork,
        user: AppUser,
        provider: str,
        correlation_id: CorrelationId,
    ) -> None:
        await uow.audit.add(
            AuditEvent(
                id=EntityId.new(),
                user_id=user.id,
                actor_type="user",
                actor_id=str(user.id),
                action="identity.login_succeeded",
                entity_type="AppUser",
                entity_id=EntityId(user.id.value),
                correlation_id=correlation_id,
                after={"provider": provider},
            )
        )
