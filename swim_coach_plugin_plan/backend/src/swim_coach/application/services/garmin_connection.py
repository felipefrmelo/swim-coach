"""Secure lifecycle for a user's Garmin connection."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from swim_coach.application.ports.garmin import GarminCredentialBootstrap
from swim_coach.application.ports.repositories import UnitOfWorkFactory
from swim_coach.domain.garmin import GarminConnection, GarminConnectionStatus
from swim_coach.domain.operations import AuditEvent
from swim_coach.domain.shared.errors import DomainError
from swim_coach.domain.shared.value_objects import CorrelationId, EntityId, UserId
from swim_coach.infrastructure.security import AesGcmSecretCipher, mask_account_label


class GarminConnectionService:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        bootstrap: GarminCredentialBootstrap,
        cipher: AesGcmSecretCipher,
    ) -> None:
        self._uow_factory = uow_factory
        self._bootstrap = bootstrap
        self._cipher = cipher

    async def connect(
        self,
        user_id: UserId,
        *,
        email: str,
        password: str,
        prompt_mfa: Callable[[], str],
    ) -> GarminConnection:
        async with self._uow_factory() as uow:
            if await uow.users.get(user_id) is None:
                raise DomainError("USER_NOT_FOUND", "The authenticated user was not found.")
        token_bundle = await self._bootstrap.authenticate(email, password, prompt_mfa)
        try:
            encrypted_token = self._cipher.encrypt(token_bundle, user_id=user_id)
        finally:
            token_bundle = b""
        now = datetime.now(UTC)
        connection = GarminConnection(
            user_id=user_id,
            status=GarminConnectionStatus.ACTIVE,
            account_label_masked=mask_account_label(email),
            encrypted_token=encrypted_token,
            provider_library_version=self._bootstrap.observed_version,
            authenticated_at=now,
        )
        async with self._uow_factory() as uow:
            await uow.garmin_connections.upsert(connection)
            await uow.audit.add(
                AuditEvent(
                    id=EntityId.new(),
                    user_id=user_id,
                    actor_type="user",
                    actor_id=str(user_id),
                    action="garmin.connection.connected",
                    entity_type="garmin_connection",
                    entity_id=None,
                    correlation_id=CorrelationId.new(),
                    after={
                        "status": "active",
                        "account_label_masked": connection.account_label_masked,
                    },
                )
            )
            await uow.commit()
        return connection

    async def status(self, user_id: UserId) -> GarminConnection | None:
        async with self._uow_factory() as uow:
            return await uow.garmin_connections.get(user_id)

    async def disconnect(self, user_id: UserId) -> GarminConnection:
        async with self._uow_factory() as uow:
            connection = await uow.garmin_connections.get(user_id)
            if connection is None:
                raise DomainError("GARMIN_NOT_CONNECTED", "No Garmin connection exists.")
            expected_version = connection.version
            before_status = connection.status.value
            connection.disconnect()
            await uow.garmin_connections.update(connection, expected_version=expected_version)
            await uow.audit.add(
                AuditEvent(
                    id=EntityId.new(),
                    user_id=user_id,
                    actor_type="user",
                    actor_id=str(user_id),
                    action="garmin.connection.disconnected",
                    entity_type="garmin_connection",
                    entity_id=None,
                    correlation_id=CorrelationId.new(),
                    before={"status": before_status},
                    after={"status": connection.status.value, "local_token_revoked": True},
                )
            )
            await uow.commit()
        return connection
