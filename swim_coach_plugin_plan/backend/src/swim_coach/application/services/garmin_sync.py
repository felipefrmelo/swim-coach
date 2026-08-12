"""Incremental, idempotent Garmin pool-swim import orchestration."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta

from swim_coach.application.ports.garmin import ActivityFilter, GarminProvider, GarminProviderError
from swim_coach.application.ports.repositories import UnitOfWorkFactory
from swim_coach.domain.athlete import Device
from swim_coach.domain.garmin import (
    Activity,
    ActivityImport,
    ActivityImportStatus,
    GarminConnectionStatus,
    RawProviderPayload,
    SyncCursor,
    SyncRun,
)
from swim_coach.domain.operations import Job
from swim_coach.domain.shared.errors import DomainError
from swim_coach.domain.shared.types import JsonObject
from swim_coach.domain.shared.value_objects import (
    Distance,
    Duration,
    EntityId,
    PoolLength,
    UserId,
)

UserLockFactory = Callable[[UserId], AbstractAsyncContextManager[None]]


class GarminSyncService:
    PROVIDER = "garmin"
    ENTITY_TYPE = "activity_summary"
    JOB_TYPE = "garmin.sync_activities"

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        provider: GarminProvider,
        user_lock: UserLockFactory,
        *,
        lookback_days: int = 90,
        overlap_seconds: int = 172_800,
        page_size: int = 20,
    ) -> None:
        self._uow_factory = uow_factory
        self._provider = provider
        self._user_lock = user_lock
        self._lookback_days = lookback_days
        self._overlap_seconds = overlap_seconds
        self._page_size = page_size

    async def request_sync(self, user_id: UserId, idempotency_key: str) -> Job:
        stable_key = (
            f"garmin-sync:{user_id}:{hashlib.sha256(idempotency_key.strip().encode()).hexdigest()}"
        )
        async with self._uow_factory() as uow:
            existing = await uow.jobs.get_by_idempotency_key(stable_key)
            if existing is not None:
                return existing
            connection = await uow.garmin_connections.get(user_id)
            if (
                connection is None
                or connection.encrypted_token is None
                or connection.status
                not in {GarminConnectionStatus.ACTIVE, GarminConnectionStatus.DEGRADED}
            ):
                raise DomainError("GARMIN_NOT_CONNECTED", "Connect Garmin before synchronizing.")
            job = Job(
                id=EntityId.new(),
                user_id=user_id,
                job_type=self.JOB_TYPE,
                payload={"user_id": str(user_id)},
                idempotency_key=stable_key,
                max_attempts=5,
            )
            job = await uow.jobs.add_idempotent(job)
            await uow.commit()
            return job

    async def _begin(self, user_id: UserId, trigger: str) -> tuple[SyncRun, SyncCursor]:
        async with self._uow_factory() as uow:
            cursor = await uow.sync_cursors.get(user_id, self.PROVIDER, self.ENTITY_TYPE)
            if cursor is None:
                cursor = SyncCursor(
                    id=EntityId.new(),
                    user_id=user_id,
                    provider=self.PROVIDER,
                    entity_type=self.ENTITY_TYPE,
                    overlap_seconds=self._overlap_seconds,
                )
            run = SyncRun(
                id=EntityId.new(),
                user_id=user_id,
                provider=self.PROVIDER,
                sync_type=self.ENTITY_TYPE,
                trigger=trigger,
                cursor_before=dict(cursor.cursor),
            )
            await uow.sync_runs.add(run)
            await uow.commit()
        return run, cursor

    @staticmethod
    def _checksum(payload: JsonObject) -> str:
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(canonical.encode()).hexdigest()

    async def _import_item(self, user_id: UserId, run: SyncRun, item: object) -> datetime:
        from swim_coach.application.ports.garmin import GarminActivitySummaryDTO

        if not isinstance(item, GarminActivitySummaryDTO):
            raise TypeError("provider returned an invalid activity DTO")
        checksum = self._checksum(item.raw_safe)
        payload = RawProviderPayload(
            id=EntityId.new(),
            user_id=user_id,
            provider=self.PROVIDER,
            entity_type=self.ENTITY_TYPE,
            external_id=item.external_id,
            content_type="application/json",
            payload=item.raw_safe,
            checksum=checksum,
            provider_updated_at=item.provider_updated_at,
        )
        async with self._uow_factory() as uow:
            raw_summary_id = await uow.raw_provider_payloads.add_if_absent(payload)
            activity = Activity(
                id=EntityId.new(),
                user_id=user_id,
                provider=self.PROVIDER,
                external_activity_id=item.external_id,
                name=item.name,
                sport=item.sport,
                subtype=item.subtype,
                start_time_utc=item.start_time_utc,
                timezone=item.timezone,
                distance=Distance(item.distance_m),
                elapsed=Duration(item.elapsed_seconds),
                timer=Duration(item.timer_seconds),
                moving=Duration(item.moving_seconds),
                pool_length=(
                    PoolLength(item.pool_length_m)
                    if item.pool_length_m is not None and item.pool_length_m > 0
                    else None
                ),
                length_count=item.length_count,
                calories=item.calories,
                avg_hr=item.avg_hr,
                max_hr=item.max_hr,
                avg_pace_seconds_per_100m=item.avg_pace_seconds_per_100m,
                avg_stroke_rate=item.avg_stroke_rate,
                avg_strokes_per_length=item.avg_strokes_per_length,
                avg_swolf=item.avg_swolf,
                source_updated_at=item.provider_updated_at,
                normalization_version="garmin-summary-v1",
                raw_summary_id=raw_summary_id,
                summary_checksum=checksum,
            )
            status, activity_id = await uow.activities.upsert(activity)
            await uow.flush()
            await uow.activity_imports.add(
                ActivityImport(
                    id=EntityId.new(),
                    user_id=user_id,
                    sync_run_id=run.id,
                    activity_id=activity_id,
                    external_activity_id=item.external_id,
                    status=status,
                    checksum=checksum,
                )
            )
            if status in {ActivityImportStatus.CREATED, ActivityImportStatus.UPDATED}:
                await uow.jobs.add_idempotent(
                    Job(
                        id=EntityId.new(),
                        user_id=user_id,
                        job_type="activity.fetch_file",
                        payload={"activity_id": str(activity_id)},
                        idempotency_key=f"activity:fetch-fit:{activity_id}:{checksum}",
                        max_attempts=5,
                    )
                )
            await uow.commit()
        if status is ActivityImportStatus.CREATED:
            run.created += 1
        elif status is ActivityImportStatus.UPDATED:
            run.updated += 1
        else:
            run.skipped += 1
        return item.start_time_utc

    async def _save_devices(self, user_id: UserId) -> None:
        devices = await self._provider.list_devices(user_id)
        now = datetime.now(UTC)
        async with self._uow_factory() as uow:
            for item in devices:
                await uow.devices.upsert(
                    Device(
                        id=EntityId.new(),
                        user_id=user_id,
                        provider=self.PROVIDER,
                        external_device_id=item.external_id,
                        model=item.model,
                        name=item.name,
                        serial_hash=item.serial_hash,
                        capabilities=item.capabilities,
                        last_seen_at=now,
                    )
                )
            await uow.commit()

    async def _finish(
        self,
        run: SyncRun,
        cursor: SyncCursor,
        watermark: datetime | None,
    ) -> None:
        now = datetime.now(UTC)
        if watermark is not None:
            cursor.watermark_at = max(
                value for value in (cursor.watermark_at, watermark) if value is not None
            )
        cursor.last_success_at = now
        cursor.updated_at = now
        cursor.cursor = {
            "watermark": cursor.watermark_at.isoformat() if cursor.watermark_at else None,
            "overlap_seconds": cursor.overlap_seconds,
        }
        cursor.version += 1
        run.finish(dict(cursor.cursor))
        async with self._uow_factory() as uow:
            await uow.sync_cursors.upsert(cursor)
            await uow.sync_runs.update(run, expected_version=1)
            await uow.commit()

    async def _fail(self, run: SyncRun, code: str, *, retryable: bool) -> None:
        run.fail(code, retryable=retryable)
        async with self._uow_factory() as uow:
            await uow.sync_runs.update(run, expected_version=1)
            await uow.commit()

    async def _cancel(self, run: SyncRun) -> None:
        run.cancel()
        async with self._uow_factory() as uow:
            await uow.sync_runs.update(run, expected_version=1)
            await uow.commit()

    async def sync(self, user_id: UserId, *, trigger: str = "worker") -> SyncRun:
        """Import a complete window; never advance the cursor after a failed run."""

        async with self._user_lock(user_id):
            run, cursor = await self._begin(user_id, trigger)
            started_after = (
                cursor.watermark_at - timedelta(seconds=cursor.overlap_seconds)
                if cursor.watermark_at
                else datetime.now(UTC) - timedelta(days=self._lookback_days)
            )
            provider_cursor: str | None = None
            watermark = cursor.watermark_at
            seen_external_ids: set[str] = set()
            try:
                while True:
                    page = await self._provider.list_activities(
                        user_id,
                        provider_cursor,
                        ActivityFilter(
                            started_after=started_after,
                            page_size=self._page_size,
                            pool_swim_only=True,
                        ),
                    )
                    run.listed += len(page.items)
                    for item in page.items:
                        if item.external_id in seen_external_ids:
                            run.skipped += 1
                            continue
                        seen_external_ids.add(item.external_id)
                        imported_at = await self._import_item(user_id, run, item)
                        watermark = (
                            imported_at if watermark is None else max(watermark, imported_at)
                        )
                    provider_cursor = page.next_cursor
                    if provider_cursor is None:
                        break
                await self._save_devices(user_id)
                if watermark is None:
                    watermark = datetime.now(UTC)
                await self._finish(run, cursor, watermark)
                return run
            except asyncio.CancelledError:
                await asyncio.shield(self._cancel(run))
                raise
            except GarminProviderError as exc:
                await self._fail(run, exc.category.value, retryable=exc.retryable)
                raise
            except Exception:
                await self._fail(run, "GARMIN_SYNC_INTERNAL", retryable=False)
                raise
