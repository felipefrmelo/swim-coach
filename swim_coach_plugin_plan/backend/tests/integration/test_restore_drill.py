from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import httpx
from sqlalchemy import text

from swim_coach.application.ports.garmin import (
    ActivityFilter,
    GarminActivitySummaryDTO,
    GarminDeviceDTO,
    GarminProviderCapabilities,
    ProviderConnectionStatus,
    ProviderPage,
)
from swim_coach.application.services import GarminSyncService, IdentityService
from swim_coach.bootstrap.api import create_app
from swim_coach.domain.shared import UserId
from swim_coach.infrastructure.backup import create_backup, restore_backup
from swim_coach.infrastructure.db import Database, SqlAlchemyUnitOfWorkFactory
from swim_coach.settings import Settings

from .test_workout_authoring import canonical_workout


class RestoreDrillGarminProvider:
    capabilities = GarminProviderCapabilities(observed_version="restore-drill-fixture")

    async def validate_connection(self, user_id: UserId) -> ProviderConnectionStatus:
        return ProviderConnectionStatus(True, False, "r***@example.test")

    async def list_devices(self, user_id: UserId) -> tuple[GarminDeviceDTO, ...]:
        return ()

    async def list_activities(
        self,
        user_id: UserId,
        cursor: str | None,
        filters: ActivityFilter,
    ) -> ProviderPage:
        if cursor is not None:
            return ProviderPage((), None)
        started = datetime(2026, 8, 12, 10, tzinfo=UTC)
        return ProviderPage(
            (
                GarminActivitySummaryDTO(
                    external_id="restore-drill-activity",
                    name="Sanitized pool swim",
                    sport="swimming",
                    subtype="lap_swimming",
                    start_time_utc=started,
                    timezone="UTC",
                    distance_m=400,
                    elapsed_seconds=Decimal("600"),
                    timer_seconds=Decimal("590"),
                    moving_seconds=Decimal("580"),
                    provider_updated_at=started,
                    pool_length_m=20,
                    length_count=20,
                    raw_safe={"activityId": "restore-drill-activity"},
                ),
            ),
            None,
        )


@asynccontextmanager
async def no_op_lock(user_id: UserId) -> AsyncIterator[None]:
    yield


def _database_url_with_name(database_url: str, database_name: str) -> str:
    parts = urlsplit(database_url.replace("postgresql+asyncpg://", "postgresql://", 1))
    return urlunsplit(
        (parts.scheme, parts.netloc, f"/{database_name}", parts.query, parts.fragment)
    )


async def test_real_encrypted_restore_preserves_login_activity_workout_and_artifact(
    database: Database,
    app_settings: Settings,
    tmp_path: Path,
) -> None:
    app = create_app(app_settings, database)
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
            login = await client.post("/api/v1/auth/dev-login")
            assert login.status_code == 204
            csrf = client.cookies["swim_coach_csrf"]
            pool = (await client.get("/api/v1/pools")).json()[0]
            workout = await client.post(
                "/api/v1/workouts",
                headers={"X-CSRF-Token": csrf},
                json={"pool_id": pool["id"], "definition": canonical_workout()},
            )
            assert workout.status_code == 201
        user = await app.state.services.identity.resolve_identity(
            provider="dev", subject="dev:first@example.test"
        )
        sync = GarminSyncService(
            app.state.services.uow_factory,
            RestoreDrillGarminProvider(),
            no_op_lock,
            lookback_days=365,
        )
        result = await sync.sync(user.id, force=True, trigger="restore-drill")
        assert result.created == 1

    artifacts = tmp_path / "source-artifacts"
    artifacts.mkdir()
    (artifacts / "sanitized.fit").write_bytes(b"restore-drill-sanitized-artifact")
    backup_path = tmp_path / "personal.scbk"
    key = bytes(range(32))
    source_url = str(app_settings.database_url).replace("postgresql+asyncpg://", "postgresql://")
    manifest = create_backup(source_url, artifacts, backup_path, key)

    restore_name = f"swim_coach_restore_{uuid4().hex}"
    admin_url = _database_url_with_name(source_url, "postgres")
    restore_url = _database_url_with_name(source_url, restore_name)
    admin = Database(admin_url)
    restored = Database(restore_url)
    try:
        async with admin.engine.connect() as connection:
            await connection.execution_options(isolation_level="AUTOCOMMIT")
            await connection.execute(text(f'CREATE DATABASE "{restore_name}"'))
        restored_artifacts = tmp_path / "restored-artifacts"
        restored_manifest = restore_backup(
            backup_path,
            restore_url,
            restored_artifacts,
            key,
        )
        async with restored.engine.connect() as connection:
            count_queries = {
                "app_user": text("SELECT count(*) FROM app_user"),
                "auth_identity": text("SELECT count(*) FROM auth_identity"),
                "activity": text("SELECT count(*) FROM activity"),
                "planned_workout": text("SELECT count(*) FROM planned_workout"),
            }
            counts = {
                table: int((await connection.execute(query)).scalar_one())
                for table, query in count_queries.items()
            }
            revision = (
                await connection.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one()
        identity = IdentityService(
            SqlAlchemyUnitOfWorkFactory(restored.session_factory),
            allowed_emails=frozenset({"first@example.test"}),
            allowed_subjects=frozenset(),
        )
        restored_user = await identity.resolve_identity(
            provider="dev", subject="dev:first@example.test"
        )
        assert restored_user.email == "first@example.test"
        assert counts == {
            "app_user": 1,
            "auth_identity": 1,
            "activity": 1,
            "planned_workout": 1,
        }
        assert revision == "000014"
        assert restored_manifest == manifest
        assert (restored_artifacts / "sanitized.fit").read_bytes() == (
            b"restore-drill-sanitized-artifact"
        )
    finally:
        await restored.dispose()
        async with admin.engine.connect() as connection:
            await connection.execution_options(isolation_level="AUTOCOMMIT")
            await connection.execute(text(f'DROP DATABASE IF EXISTS "{restore_name}" WITH (FORCE)'))
        await admin.dispose()
