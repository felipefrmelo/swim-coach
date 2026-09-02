from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import delete, func, select

from swim_coach.application.ports.garmin import (
    ActivityFilter,
    GarminActivitySummaryDTO,
    GarminDeviceDTO,
    GarminProviderCapabilities,
    ProviderConnectionStatus,
    ProviderPage,
)
from swim_coach.application.services import GarminSyncService, IdentityService
from swim_coach.domain.activities import SessionFeedback
from swim_coach.domain.garmin import GarminConnection, GarminConnectionStatus
from swim_coach.domain.shared import CorrelationId, EncryptedSecret, UserId
from swim_coach.domain.shared.errors import DomainError
from swim_coach.domain.shared.value_objects import EntityId
from swim_coach.infrastructure.db import Database, SqlAlchemyUnitOfWorkFactory
from swim_coach.infrastructure.db.models import (
    ActivityImportModel,
    ActivityModel,
    JobModel,
    RawProviderPayloadModel,
    SessionFeedbackModel,
    SyncCursorModel,
    SyncRunModel,
)


class FixtureGarminProvider:
    capabilities = GarminProviderCapabilities(observed_version="fixture")

    async def validate_connection(self, user_id: UserId) -> ProviderConnectionStatus:
        return ProviderConnectionStatus(True, False, "a***@example.test")

    async def list_devices(self, user_id: UserId) -> tuple[GarminDeviceDTO, ...]:
        return (GarminDeviceDTO("device-1", "Forerunner 265", "Forerunner 265"),)

    async def list_activities(
        self,
        user_id: UserId,
        cursor: str | None,
        filters: ActivityFilter,
    ) -> ProviderPage:
        index = int(cursor or "0")
        if index >= 2:
            return ProviderPage((), None)
        started_at = datetime(2026, 8, 10 - index, 21, tzinfo=UTC)
        item = GarminActivitySummaryDTO(
            external_id=f"activity-{index + 1}",
            name=f"Pool swim {index + 1}",
            sport="swimming",
            subtype="lap_swimming",
            start_time_utc=started_at,
            timezone="UTC",
            distance_m=2000,
            elapsed_seconds=Decimal("2700"),
            timer_seconds=Decimal("2700"),
            moving_seconds=Decimal("2680"),
            provider_updated_at=started_at,
            pool_length_m=20,
            length_count=100,
            raw_safe={
                "activityId": f"activity-{index + 1}",
                "activityType": {"typeKey": "lap_swimming"},
                "distance": 2000,
            },
        )
        return ProviderPage((item,), str(index + 1) if index == 0 else None)


class BlockingGarminProvider(FixtureGarminProvider):
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.block = asyncio.Event()

    async def list_activities(
        self,
        user_id: UserId,
        cursor: str | None,
        filters: ActivityFilter,
    ) -> ProviderPage:
        self.started.set()
        await self.block.wait()
        return ProviderPage((), None)


@asynccontextmanager
async def no_op_user_lock(user_id: UserId) -> AsyncIterator[None]:
    yield


async def test_incremental_sync_paginates_and_replay_deduplicates(database: Database) -> None:
    uow_factory = SqlAlchemyUnitOfWorkFactory(database.session_factory)
    identity = IdentityService(
        uow_factory,
        allowed_emails=frozenset({"first@example.test"}),
        allowed_subjects=frozenset(),
    )
    user = await identity.ensure_identity(
        provider="test-oidc",
        subject="garmin-user",
        email="first@example.test",
        display_name="Swimmer",
        claims_snapshot={"email_verified": True},
        correlation_id=CorrelationId.new(),
    )
    service = GarminSyncService(
        uow_factory,
        FixtureGarminProvider(),
        no_op_user_lock,
        lookback_days=365,
        page_size=1,
    )

    first = await service.sync(user.id, trigger="test")
    replay = await service.sync(user.id, trigger="test")

    assert (first.created, first.updated, first.skipped) == (2, 0, 0)
    assert (replay.created, replay.updated, replay.skipped) == (0, 0, 2)
    async with database.session_factory() as session:
        activity_count = await session.scalar(select(func.count()).select_from(ActivityModel))
        payload_count = await session.scalar(
            select(func.count()).select_from(RawProviderPayloadModel)
        )
        import_count = await session.scalar(select(func.count()).select_from(ActivityImportModel))
        cursor_count = await session.scalar(select(func.count()).select_from(SyncCursorModel))
    assert activity_count == 2
    assert payload_count == 2
    assert import_count == 4
    assert cursor_count == 1


async def test_sync_relinks_feedback_after_activity_reimport(database: Database) -> None:
    uow_factory = SqlAlchemyUnitOfWorkFactory(database.session_factory)
    identity = IdentityService(
        uow_factory,
        allowed_emails=frozenset({"first@example.test"}),
        allowed_subjects=frozenset(),
    )
    user = await identity.ensure_identity(
        provider="test-oidc",
        subject="feedback-reimport-user",
        email="first@example.test",
        display_name="Swimmer",
        claims_snapshot={"email_verified": True},
        correlation_id=CorrelationId.new(),
    )
    service = GarminSyncService(
        uow_factory,
        FixtureGarminProvider(),
        no_op_user_lock,
        lookback_days=365,
        page_size=1,
    )
    await service.sync(user.id, trigger="test")
    async with uow_factory() as uow:
        original = next(
            item
            for item in await uow.activities.list_recent(user.id)
            if item.external_activity_id == "activity-1"
        )
        feedback = SessionFeedback(
            id=EntityId.new(),
            user_id=user.id,
            activity_id=original.id,
            provider=original.provider,
            external_activity_id=original.external_activity_id,
            rpe=7,
            technique_rating=3,
            pain_present=False,
            comment="Feedback must survive a Garmin reimport.",
        )
        await uow.activity_data.upsert_feedback(feedback, expected_version=None)
        await uow.commit()

    async with database.session_factory.begin() as session:
        await session.execute(delete(ActivityModel).where(ActivityModel.id == original.id.value))
    async with database.session_factory() as session:
        detached_activity_id = await session.scalar(
            select(SessionFeedbackModel.activity_id).where(
                SessionFeedbackModel.id == feedback.id.value
            )
        )
    assert detached_activity_id is None

    replay = await service.sync(user.id, trigger="test-reimport", force=True)
    assert replay.created == 1
    async with uow_factory() as uow:
        replacement = next(
            item
            for item in await uow.activities.list_recent(user.id)
            if item.external_activity_id == "activity-1"
        )
        restored = await uow.activity_data.get_feedback(user.id, replacement.id)

    assert replacement.id != original.id
    assert restored is not None
    assert restored.id == feedback.id
    assert restored.rpe == 7
    assert restored.comment == "Feedback must survive a Garmin reimport."


async def test_cancelled_sync_records_terminal_run_without_advancing_cursor(
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
        subject="cancelled-garmin-user",
        email="first@example.test",
        display_name="Swimmer",
        claims_snapshot={"email_verified": True},
        correlation_id=CorrelationId.new(),
    )
    provider = BlockingGarminProvider()
    service = GarminSyncService(uow_factory, provider, no_op_user_lock)
    task = asyncio.create_task(service.sync(user.id, trigger="test"))
    await asyncio.wait_for(provider.started.wait(), timeout=1)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    async with database.session_factory() as session:
        statuses = list(
            await session.scalars(
                select(SyncRunModel.status).where(SyncRunModel.user_id == user.id.value)
            )
        )
        cursor_count = await session.scalar(
            select(func.count())
            .select_from(SyncCursorModel)
            .where(SyncCursorModel.user_id == user.id.value)
        )
    assert statuses == ["cancelled"]
    assert cursor_count == 0


async def test_sync_request_is_atomic_for_same_idempotency_key(database: Database) -> None:
    uow_factory = SqlAlchemyUnitOfWorkFactory(database.session_factory)
    identity = IdentityService(
        uow_factory,
        allowed_emails=frozenset({"first@example.test"}),
        allowed_subjects=frozenset(),
    )
    user = await identity.ensure_identity(
        provider="test-oidc",
        subject="idempotent-garmin-user",
        email="first@example.test",
        display_name="Swimmer",
        claims_snapshot={"email_verified": True},
        correlation_id=CorrelationId.new(),
    )
    async with uow_factory() as uow:
        await uow.garmin_connections.upsert(
            GarminConnection(
                user_id=user.id,
                status=GarminConnectionStatus.ACTIVE,
                account_label_masked="a***@example.test",
                encrypted_token=EncryptedSecret(b"x" * 16, b"n" * 12, "v1"),
                provider_library_version="fixture",
            )
        )
        await uow.commit()
    service = GarminSyncService(uow_factory, FixtureGarminProvider(), no_op_user_lock)

    first, replay = await asyncio.gather(
        service.request_sync(user.id, "same-request-key"),
        service.request_sync(user.id, "same-request-key"),
    )

    assert first.id == replay.id
    async with database.session_factory() as session:
        job_count = await session.scalar(
            select(func.count()).select_from(JobModel).where(JobModel.user_id == user.id.value)
        )
    assert job_count == 1

    with pytest.raises(DomainError) as captured:
        await service.request_sync(
            user.id,
            "same-request-key",
            from_date=date(2026, 8, 1),
            force=True,
        )
    assert getattr(captured.value, "code", None) == "IDEMPOTENCY_CONFLICT"
