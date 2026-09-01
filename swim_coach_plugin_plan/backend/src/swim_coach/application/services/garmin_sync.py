"""Incremental, idempotent Garmin pool-swim import orchestration."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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
from swim_coach.domain.shared.types import JsonObject, JsonValue
from swim_coach.domain.shared.value_objects import (
    Distance,
    Duration,
    EntityId,
    PoolLength,
    UserId,
)

UserLockFactory = Callable[[UserId], AbstractAsyncContextManager[None]]
LOGGER = logging.getLogger(__name__)


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

    async def request_sync(
        self,
        user_id: UserId,
        idempotency_key: str,
        *,
        from_date: date | None = None,
        force: bool = False,
    ) -> Job:
        stable_key = (
            f"garmin-sync:{user_id}:{hashlib.sha256(idempotency_key.strip().encode()).hexdigest()}"
        )
        requested_payload: JsonObject = {
            "user_id": str(user_id),
            "from_date": from_date.isoformat() if from_date else None,
            "force": force,
        }
        async with self._uow_factory() as uow:
            existing = await uow.jobs.get_by_idempotency_key(stable_key)
            if existing is not None:
                if existing.payload != requested_payload:
                    raise DomainError(
                        "IDEMPOTENCY_CONFLICT",
                        "This idempotency key was already used for a different sync request.",
                    )
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
                payload=requested_payload,
                idempotency_key=stable_key,
                max_attempts=5,
            )
            job = await uow.jobs.add_idempotent(job)
            if job.payload != requested_payload:
                raise DomainError(
                    "IDEMPOTENCY_CONFLICT",
                    "This idempotency key was already used for a different sync request.",
                )
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
        async with self._uow_factory() as uow:
            user = await uow.users.get(user_id)
            activity_timezone = user.timezone if user is not None else (item.timezone or "UTC")
            semantic_warnings: list[JsonValue] = list(item.warnings)
            try:
                zone = ZoneInfo(activity_timezone)
            except ZoneInfoNotFoundError:
                zone = ZoneInfo("UTC")
                semantic_warnings.append("ATHLETE_TIMEZONE_INVALID_FALLBACK_UTC")
            expected_local_wall = item.start_time_utc.astimezone(zone).replace(tzinfo=None)
            if (
                item.start_time_local_wall is not None
                and item.start_time_local_wall != expected_local_wall
            ):
                semantic_warnings.append("GARMIN_LOCAL_WALL_TIME_MISMATCH")
            raw_payload: JsonObject = dict(item.raw_safe)
            semantics: JsonObject = {
                "provenance": item.provenance,
                "warnings": semantic_warnings,
                "athlete_timezone": activity_timezone,
                "expected_local_wall": expected_local_wall.isoformat(),
            }
            raw_payload["_swim_coach_semantics"] = semantics
            checksum = self._checksum(raw_payload)
            payload = RawProviderPayload(
                id=EntityId.new(),
                user_id=user_id,
                provider=self.PROVIDER,
                entity_type=self.ENTITY_TYPE,
                external_id=item.external_id,
                content_type="application/json",
                payload=raw_payload,
                checksum=checksum,
                provider_updated_at=item.provider_updated_at,
            )
            raw_summary_id = await uow.raw_provider_payloads.add_if_absent(payload)
            legacy_moving = (
                item.moving_seconds if item.moving_seconds is not None else item.timer_seconds
            )
            activity = Activity(
                id=EntityId.new(),
                user_id=user_id,
                provider=self.PROVIDER,
                external_activity_id=item.external_id,
                name=item.name,
                sport=item.sport,
                subtype=item.subtype,
                start_time_utc=item.start_time_utc,
                # Garmin's startTimeLocal is a wall-clock value without a
                # trustworthy IANA zone.  The athlete profile owns that zone;
                # the raw local value remains in RawProviderPayload for audit.
                timezone=activity_timezone,
                distance=Distance(item.distance_m),
                elapsed=Duration(item.elapsed_seconds),
                timer=Duration(item.timer_seconds),
                # Activity is the legacy summary model and still requires a
                # value.  The v2 normalization never consumes this fallback as
                # a Garmin moving fact; provenance above marks it explicitly.
                moving=Duration(legacy_moving),
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
                normalization_version="garmin-summary-v2",
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
        LOGGER.info(
            "garmin_activity_summary_imported",
            extra={
                "activity_id": str(activity_id),
                "garmin_activity_id_hash": hashlib.sha256(item.external_id.encode()).hexdigest(),
                "raw_pool_length": item.raw_safe.get("poolLength"),
                "normalized_pool_length_m": item.pool_length_m,
                "distance_m": item.distance_m,
                "elapsed_duration_s": format(item.elapsed_seconds, "f"),
                "timer_duration_s": format(item.timer_seconds, "f"),
                "moving_duration_s": (
                    format(item.moving_seconds, "f") if item.moving_seconds is not None else None
                ),
                "length_count": item.length_count,
                "normalization_warnings": semantic_warnings,
            },
        )
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

    async def sync(
        self,
        user_id: UserId,
        *,
        trigger: str = "worker",
        from_date: date | None = None,
        force: bool = False,
    ) -> SyncRun:
        """Import a complete window; never advance the cursor after a failed run."""

        async with self._user_lock(user_id):
            run, cursor = await self._begin(user_id, trigger)
            requested_start = (
                datetime.combine(from_date, time.min, tzinfo=UTC) if from_date else None
            )
            started_after = (
                requested_start
                if requested_start is not None
                else datetime.now(UTC) - timedelta(days=self._lookback_days)
                if force or cursor.watermark_at is None
                else cursor.watermark_at - timedelta(seconds=cursor.overlap_seconds)
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
