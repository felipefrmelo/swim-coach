from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import select

from swim_coach.application.services import GarminConnectionService, IdentityService
from swim_coach.domain.garmin import GarminConnectionStatus
from swim_coach.domain.shared import CorrelationId
from swim_coach.infrastructure.db import Database, SqlAlchemyUnitOfWorkFactory
from swim_coach.infrastructure.db.models import GarminConnectionModel
from swim_coach.infrastructure.security import AesGcmSecretCipher


class FixtureBootstrap:
    observed_version = "fixture-1"

    async def authenticate(
        self,
        email: str,
        password: str,
        prompt_mfa: Callable[[], str],
    ) -> bytes:
        assert email == "athlete@example.test"
        assert password == "not-persisted"  # noqa: S105 - synthetic assertion
        return b'{"oauth1":"fixture-secret-token"}'


async def test_connection_encrypts_token_and_disconnect_revokes_local_access(
    database: Database,
) -> None:
    uow_factory = SqlAlchemyUnitOfWorkFactory(database.session_factory)
    identity = IdentityService(
        uow_factory,
        allowed_emails=frozenset({"first@example.test"}),
        allowed_subjects=frozenset(),
    )
    user = await identity.ensure_identity(
        provider="test-oidc",
        subject="connection-user",
        email="first@example.test",
        display_name="Swimmer",
        claims_snapshot={"email_verified": True},
        correlation_id=CorrelationId.new(),
    )
    service = GarminConnectionService(
        uow_factory,
        FixtureBootstrap(),
        AesGcmSecretCipher({"v1": b"k" * 32}, "v1"),
    )

    connected = await service.connect(
        user.id,
        email="athlete@example.test",
        password="not-persisted",  # noqa: S106 - synthetic fixture value
        prompt_mfa=lambda: "000000",
    )
    assert connected.status is GarminConnectionStatus.ACTIVE
    assert connected.account_label_masked == "a***@example.test"

    async with database.session_factory() as session:
        stored = (
            await session.scalars(
                select(GarminConnectionModel).where(GarminConnectionModel.user_id == user.id.value)
            )
        ).one()
        assert stored.encrypted_token_bundle is not None
        assert b"fixture-secret-token" not in stored.encrypted_token_bundle
        assert stored.token_key_version == "v1"  # noqa: S105 - key identifier, not a secret

    disconnected = await service.disconnect(user.id)
    assert disconnected.status is GarminConnectionStatus.DISCONNECTED
    assert disconnected.encrypted_token is None
    async with database.session_factory() as session:
        stored = await session.get(GarminConnectionModel, user.id.value)
        assert stored is not None
        assert stored.encrypted_token_bundle is None
        assert stored.token_nonce is None
        assert stored.token_key_version is None
