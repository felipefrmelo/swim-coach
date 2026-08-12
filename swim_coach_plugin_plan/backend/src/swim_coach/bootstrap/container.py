"""Composition of P01 application services."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import timedelta

from swim_coach.application.services import (
    ContextService,
    GarminConnectionService,
    GarminSyncService,
    IdentityService,
    SessionService,
)
from swim_coach.application.services.oidc_login import OidcLoginService
from swim_coach.domain.shared.value_objects import UserId
from swim_coach.infrastructure.auth import OidcClient
from swim_coach.infrastructure.db import Database, SqlAlchemyUnitOfWorkFactory
from swim_coach.infrastructure.garmin import GarminConnectBootstrap, GarminConnectProvider
from swim_coach.infrastructure.security import AesGcmSecretCipher
from swim_coach.settings import Settings


@dataclass(frozen=True, slots=True)
class AppServices:
    database: Database
    uow_factory: SqlAlchemyUnitOfWorkFactory
    context: ContextService
    identity: IdentityService
    sessions: SessionService
    oidc_login: OidcLoginService | None
    garmin_connection: GarminConnectionService | None
    garmin_sync: GarminSyncService | None


def build_services(settings: Settings, database: Database | None = None) -> AppServices:
    database = database or Database(str(settings.database_url))
    uow_factory = SqlAlchemyUnitOfWorkFactory(database.session_factory)
    identity = IdentityService(
        uow_factory,
        allowed_emails=settings.allowed_emails,
        allowed_subjects=settings.allowed_subjects,
    )
    sessions = SessionService(
        uow_factory,
        lifetime=timedelta(hours=settings.session_lifetime_hours),
    )
    oidc_login: OidcLoginService | None = None
    garmin_connection: GarminConnectionService | None = None
    garmin_sync: GarminSyncService | None = None
    if settings.oidc_issuer is not None and settings.oidc_client_id is not None:
        client_secret = (
            settings.oidc_client_secret.get_secret_value()
            if settings.oidc_client_secret is not None
            else None
        )
        oidc_login = OidcLoginService(
            uow_factory=uow_factory,
            oidc_client=OidcClient(
                issuer=str(settings.oidc_issuer),
                client_id=settings.oidc_client_id,
                client_secret=client_secret,
            ),
            identity_service=identity,
            session_service=sessions,
            redirect_uri=settings.oidc_redirect_uri,
        )
    if settings.garmin_active_key_version is not None:
        cipher = AesGcmSecretCipher(
            settings.garmin_keyring,
            settings.garmin_active_key_version,
        )
        provider = GarminConnectProvider(uow_factory, database, cipher)

        def user_sync_lock(user_id: UserId) -> AbstractAsyncContextManager[None]:
            return database.user_advisory_lock(f"garmin-sync:{user_id}")

        garmin_connection = GarminConnectionService(
            uow_factory,
            GarminConnectBootstrap(),
            cipher,
        )
        garmin_sync = GarminSyncService(
            uow_factory,
            provider,
            user_sync_lock,
            lookback_days=settings.garmin_sync_lookback_days,
            overlap_seconds=settings.garmin_sync_overlap_seconds,
        )
    return AppServices(
        database=database,
        uow_factory=uow_factory,
        context=ContextService(uow_factory),
        identity=identity,
        sessions=sessions,
        oidc_login=oidc_login,
        garmin_connection=garmin_connection,
        garmin_sync=garmin_sync,
    )
