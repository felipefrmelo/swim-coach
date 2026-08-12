"""Composition of P01 application services."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import timedelta

from swim_coach.application.ports.garmin import GarminWorkoutProvider
from swim_coach.application.services import (
    ActivityDataService,
    AutomationService,
    ContextService,
    GarminConnectionService,
    GarminPublishService,
    GarminSyncService,
    IdentityService,
    McpReadService,
    McpWriteService,
    PlanningService,
    SessionService,
    WorkoutService,
)
from swim_coach.application.services.oidc_login import OidcLoginService
from swim_coach.domain.shared.value_objects import UserId
from swim_coach.infrastructure.auth import OidcClient
from swim_coach.infrastructure.db import Database, SqlAlchemyUnitOfWorkFactory
from swim_coach.infrastructure.fit import GarminFitActivityParser
from swim_coach.infrastructure.garmin import (
    FakeGarminWorkoutProvider,
    GarminConnectBootstrap,
    GarminConnectProvider,
)
from swim_coach.infrastructure.security import AesGcmSecretCipher
from swim_coach.infrastructure.storage import FilesystemObjectStorage
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
    garmin_publish: GarminPublishService
    garmin_writer: GarminWorkoutProvider | None
    workouts: WorkoutService
    activity_data: ActivityDataService
    mcp_read: McpReadService
    mcp_write: McpWriteService | None
    planning: PlanningService | None
    automation: AutomationService | None


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
    garmin_writer: GarminWorkoutProvider | None = None
    garmin_reader: GarminConnectProvider | None = None
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
        garmin_reader = provider

        def user_sync_lock(user_id: UserId) -> AbstractAsyncContextManager[None]:
            return database.user_advisory_lock(f"garmin-sync:{user_id}")

        garmin_connection = GarminConnectionService(
            uow_factory,
            GarminConnectBootstrap(),
            cipher,
        )
        if settings.garmin_read_enabled:
            garmin_sync = GarminSyncService(
                uow_factory,
                provider,
                user_sync_lock,
                lookback_days=settings.garmin_sync_lookback_days,
                overlap_seconds=settings.garmin_sync_overlap_seconds,
            )
        if settings.garmin_write_enabled and settings.garmin_write_mode == "live":
            garmin_writer = provider
    if settings.garmin_write_enabled and settings.garmin_write_mode == "fake":
        garmin_writer = FakeGarminWorkoutProvider()
    context = ContextService(uow_factory)
    workouts = WorkoutService(uow_factory)
    activity_data = ActivityDataService(
        uow_factory,
        garmin_reader,
        FilesystemObjectStorage(settings.activity_storage_path),
        GarminFitActivityParser(),
    )
    garmin_publish = GarminPublishService(
        uow_factory,
        write_enabled=settings.garmin_write_enabled,
        allow_fake_device=settings.garmin_write_mode == "fake",
        canary_title_prefix=(
            settings.garmin_write_canary_title_prefix
            if settings.garmin_write_mode == "live" and settings.garmin_write_canary_only
            else None
        ),
    )
    mcp_read = McpReadService(
        uow_factory=uow_factory,
        identity=identity,
        context=context,
        workouts=workouts,
        activity_data=activity_data,
    )
    planning = PlanningService(uow_factory) if settings.planning_enabled else None
    automation = (
        AutomationService(
            uow_factory,
            sync_hour=settings.automation_sync_hour,
            planning_weekday=settings.automation_planning_weekday,
            planning_hour=settings.automation_planning_hour,
            retention_days=settings.job_retention_days,
            sync_enabled=garmin_sync is not None,
            planning_enabled=planning is not None,
        )
        if settings.automation_enabled
        else None
    )
    return AppServices(
        database=database,
        uow_factory=uow_factory,
        context=context,
        identity=identity,
        sessions=sessions,
        oidc_login=oidc_login,
        garmin_connection=garmin_connection,
        garmin_sync=garmin_sync,
        garmin_publish=garmin_publish,
        garmin_writer=garmin_writer,
        workouts=workouts,
        activity_data=activity_data,
        mcp_read=mcp_read,
        planning=planning,
        automation=automation,
        mcp_write=(
            McpWriteService(
                uow_factory=uow_factory,
                workouts=workouts,
                activity_data=activity_data,
                garmin_sync=garmin_sync,
                garmin_publish=garmin_publish,
                planning=planning,
            )
            if settings.mcp_write_enabled
            else None
        ),
    )
