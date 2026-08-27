"""Unofficial Garmin Connect adapter with external types confined to this module."""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import importlib.metadata
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, TypeVar, cast

from swim_coach.application.ports.garmin import (
    ActivityFilter,
    ExternalScheduleResult,
    ExternalWorkoutResult,
    GarminActivityFileDTO,
    GarminActivitySummaryDTO,
    GarminDeviceDTO,
    GarminErrorCategory,
    GarminProviderCapabilities,
    GarminProviderError,
    GarminWorkoutDTO,
    ProviderConnectionStatus,
    ProviderPage,
)
from swim_coach.application.ports.repositories import UnitOfWorkFactory
from swim_coach.domain.garmin import GarminConnectionStatus
from swim_coach.domain.shared.types import JsonObject, JsonValue
from swim_coach.domain.shared.value_objects import UserId
from swim_coach.infrastructure.db import Database
from swim_coach.infrastructure.security import AesGcmSecretCipher

T = TypeVar("T")
_POOL_SWIM_TYPES = frozenset({"lap_swimming", "pool_swimming"})
_SAFE_ACTIVITY_FIELDS = (
    "activityId",
    "activityName",
    "activityType",
    "startTimeGMT",
    "startTimeLocal",
    "distance",
    "duration",
    "elapsedDuration",
    "movingDuration",
    "poolLength",
    "numberOfActiveLengths",
    "calories",
    "averageHR",
    "maxHR",
    "averagePace",
    "averageSwimCadenceInStrokesPerMinute",
    "avgStrokes",
    "avgSwolf",
    "lastUpdated",
)


def _decimal(value: object, *, default: Decimal | None = None) -> Decimal | None:
    if value is None:
        return default
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise GarminProviderError(GarminErrorCategory.SCHEMA_CHANGED, retryable=False) from exc
    if not result.is_finite() or result < 0:
        raise GarminProviderError(GarminErrorCategory.SCHEMA_CHANGED, retryable=False)
    return result


def _integer(value: object) -> int | None:
    number = _decimal(value)
    if number is None:
        return None
    return int(number)


def _utc_datetime(value: object) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise GarminProviderError(GarminErrorCategory.SCHEMA_CHANGED, retryable=False)
    normalized = value.strip().replace("Z", "+00:00")
    try:
        result = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise GarminProviderError(GarminErrorCategory.SCHEMA_CHANGED, retryable=False) from exc
    if result.tzinfo is None:
        result = result.replace(tzinfo=UTC)
    return result.astimezone(UTC)


def _optional_utc_datetime(value: object) -> datetime | None:
    return None if value is None else _utc_datetime(value)


def _json_safe(value: object) -> JsonValue:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe(item) for item in value]
    return str(value)


def map_activity(raw: Mapping[str, Any]) -> GarminActivitySummaryDTO:
    activity_type = raw.get("activityType")
    if not isinstance(activity_type, Mapping):
        raise GarminProviderError(GarminErrorCategory.SCHEMA_CHANGED, retryable=False)
    subtype = activity_type.get("typeKey")
    external_id = raw.get("activityId")
    if not isinstance(subtype, str) or not isinstance(external_id, str | int):
        raise GarminProviderError(GarminErrorCategory.SCHEMA_CHANGED, retryable=False)
    elapsed = cast(
        Decimal, _decimal(raw.get("elapsedDuration", raw.get("duration")), default=Decimal(0))
    )
    timer = cast(Decimal, _decimal(raw.get("duration"), default=elapsed))
    moving = cast(Decimal, _decimal(raw.get("movingDuration"), default=timer))
    distance = _integer(raw.get("distance")) or 0
    start_time = _utc_datetime(raw.get("startTimeGMT"))
    safe_raw: JsonObject = {
        field: _json_safe(raw[field]) for field in _SAFE_ACTIVITY_FIELDS if field in raw
    }
    return GarminActivitySummaryDTO(
        external_id=str(external_id),
        name=str(raw.get("activityName") or "Pool swim")[:255],
        sport="swimming",
        subtype=subtype,
        start_time_utc=start_time,
        timezone="UTC",
        distance_m=distance,
        elapsed_seconds=elapsed,
        timer_seconds=timer,
        moving_seconds=moving,
        provider_updated_at=_optional_utc_datetime(raw.get("lastUpdated")),
        pool_length_m=_integer(raw.get("poolLength")),
        length_count=_integer(raw.get("numberOfActiveLengths")),
        calories=_integer(raw.get("calories")),
        avg_hr=_integer(raw.get("averageHR")),
        max_hr=_integer(raw.get("maxHR")),
        avg_pace_seconds_per_100m=_decimal(raw.get("averagePace")),
        avg_stroke_rate=_decimal(raw.get("averageSwimCadenceInStrokesPerMinute")),
        avg_strokes_per_length=_decimal(raw.get("avgStrokes")),
        avg_swolf=_decimal(raw.get("avgSwolf")),
        raw_safe=safe_raw,
    )


class GarminConnectProvider:
    """Authenticate exclusively from an encrypted token and expose read operations."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        database: Database,
        cipher: AesGcmSecretCipher,
    ) -> None:
        self._uow_factory = uow_factory
        self._database = database
        self._cipher = cipher
        try:
            observed_version = importlib.metadata.version("garminconnect")
        except importlib.metadata.PackageNotFoundError:
            observed_version = "unknown"
        self._capabilities = GarminProviderCapabilities(
            file_read=True, workout_write=True, observed_version=observed_version
        )

    @property
    def capabilities(self) -> GarminProviderCapabilities:
        return self._capabilities

    async def _connection(self, user_id: UserId) -> tuple[bytes, int]:
        async with self._uow_factory() as uow:
            connection = await uow.garmin_connections.get(user_id)
        if (
            connection is None
            or connection.encrypted_token is None
            or connection.status
            not in {GarminConnectionStatus.ACTIVE, GarminConnectionStatus.DEGRADED}
        ):
            raise GarminProviderError(GarminErrorCategory.AUTH_REQUIRED, retryable=False)
        return (
            self._cipher.decrypt(connection.encrypted_token, user_id=user_id),
            connection.version,
        )

    @staticmethod
    def _sync_call(token: bytes, operation: Callable[[Any], T]) -> tuple[T, bytes]:
        module = importlib.import_module("garminconnect")
        client = module.Garmin()
        token_text = token.decode()
        try:
            client.login(token_text)
            result = operation(client)
            refreshed_token = str(client.client.dumps()).encode()
            return result, refreshed_token
        finally:
            token_text = ""

    @staticmethod
    def _provider_error(exc: Exception) -> GarminProviderError:
        if isinstance(exc, GarminProviderError):
            return exc
        name = type(exc).__name__
        if name == "GarminConnectAuthenticationError":
            return GarminProviderError(GarminErrorCategory.AUTH_REQUIRED, retryable=False)
        if name == "GarminConnectTooManyRequestsError":
            return GarminProviderError(
                GarminErrorCategory.RATE_LIMITED,
                retryable=True,
                retry_after_seconds=900,
            )
        if name == "GarminConnectNotFoundError":
            return GarminProviderError(GarminErrorCategory.NOT_FOUND, retryable=False)
        if name == "GarminConnectConnectionError":
            return GarminProviderError(GarminErrorCategory.NETWORK, retryable=True)
        return GarminProviderError(GarminErrorCategory.UNKNOWN, retryable=False)

    async def _mark_error(self, user_id: UserId, error: GarminProviderError) -> None:
        async with self._uow_factory() as uow:
            connection = await uow.garmin_connections.get(user_id)
            if connection is None:
                return
            expected_version = connection.version
            connection.mark_error(
                error.category.value,
                reauth_required=error.category is GarminErrorCategory.AUTH_REQUIRED,
            )
            await uow.garmin_connections.update(connection, expected_version=expected_version)
            await uow.commit()

    async def _persist_success(self, user_id: UserId, refreshed_token: bytes) -> None:
        async with self._uow_factory() as uow:
            connection = await uow.garmin_connections.get(user_id)
            if connection is None or connection.encrypted_token is None:
                raise GarminProviderError(GarminErrorCategory.AUTH_REQUIRED, retryable=False)
            expected_version = connection.version
            current_token = self._cipher.decrypt(connection.encrypted_token, user_id=user_id)
            token_changed = current_token != refreshed_token
            rotation_needed = connection.encrypted_token.key_version != self._cipher.active_version
            if token_changed or rotation_needed:
                connection.encrypted_token = self._cipher.encrypt(
                    refreshed_token,
                    user_id=user_id,
                )
            connection.mark_success(refreshed=token_changed or rotation_needed)
            await uow.garmin_connections.update(connection, expected_version=expected_version)
            await uow.commit()

    async def _call(self, user_id: UserId, operation: Callable[[Any], T]) -> T:
        async with self._database.user_advisory_lock(str(user_id)):
            token, _ = await self._connection(user_id)
            try:
                result, refreshed_token = await asyncio.to_thread(self._sync_call, token, operation)
                await self._persist_success(user_id, refreshed_token)
                return result
            except Exception as exc:
                error = self._provider_error(exc)
                await self._mark_error(user_id, error)
                raise error from exc
            finally:
                token = b""

    async def validate_connection(self, user_id: UserId) -> ProviderConnectionStatus:
        async with self._uow_factory() as uow:
            connection = await uow.garmin_connections.get(user_id)
        if connection is None:
            return ProviderConnectionStatus(False, False, "***")
        if connection.status in {
            GarminConnectionStatus.ACTIVE,
            GarminConnectionStatus.DEGRADED,
        }:
            await self._call(user_id, lambda client: client.get_devices())
            return ProviderConnectionStatus(True, False, connection.account_label_masked)
        return ProviderConnectionStatus(
            False,
            connection.status is GarminConnectionStatus.REAUTH_REQUIRED,
            connection.account_label_masked,
        )

    async def list_devices(self, user_id: UserId) -> tuple[GarminDeviceDTO, ...]:
        raw_devices = await self._call(user_id, lambda client: client.get_devices())
        result: list[GarminDeviceDTO] = []
        for raw in raw_devices:
            if not isinstance(raw, Mapping):
                raise GarminProviderError(GarminErrorCategory.SCHEMA_CHANGED, retryable=False)
            external_id = raw.get("deviceId", raw.get("unitId"))
            model = raw.get("productDisplayName", raw.get("displayName"))
            if not isinstance(external_id, str | int) or not isinstance(model, str):
                raise GarminProviderError(GarminErrorCategory.SCHEMA_CHANGED, retryable=False)
            serial = raw.get("serialNumber")
            result.append(
                GarminDeviceDTO(
                    external_id=str(external_id),
                    model=model[:120],
                    name=str(raw.get("displayName") or model)[:120],
                    serial_hash=(
                        hashlib.sha256(str(serial).encode()).hexdigest() if serial else None
                    ),
                    capabilities={"activity_read": True, "workout_write": False},
                )
            )
        return tuple(result)

    async def list_activities(
        self,
        user_id: UserId,
        cursor: str | None,
        filters: ActivityFilter,
    ) -> ProviderPage:
        try:
            offset = int(cursor or "0")
        except ValueError as exc:
            raise GarminProviderError(GarminErrorCategory.SCHEMA_CHANGED, retryable=False) from exc
        if offset < 0:
            raise GarminProviderError(GarminErrorCategory.SCHEMA_CHANGED, retryable=False)
        raw_items = await self._call(
            user_id,
            lambda client: client.get_activities(offset, filters.page_size),
        )
        mapped: list[GarminActivitySummaryDTO] = []
        boundary_reached = False
        for raw in raw_items:
            if not isinstance(raw, Mapping):
                raise GarminProviderError(GarminErrorCategory.SCHEMA_CHANGED, retryable=False)
            raw_start_time = _utc_datetime(raw.get("startTimeGMT"))
            if filters.started_after is not None and raw_start_time <= filters.started_after:
                boundary_reached = True
                continue
            activity_type = raw.get("activityType")
            type_key = activity_type.get("typeKey") if isinstance(activity_type, Mapping) else None
            if filters.pool_swim_only and type_key not in _POOL_SWIM_TYPES:
                continue
            item = map_activity(raw)
            mapped.append(item)
        next_cursor = None
        if len(raw_items) == filters.page_size and not boundary_reached:
            next_cursor = str(offset + filters.page_size)
        return ProviderPage(tuple(mapped), next_cursor)

    async def download_activity_file(
        self, user_id: UserId, external_activity_id: str
    ) -> GarminActivityFileDTO:
        if not external_activity_id.isdecimal() or int(external_activity_id) <= 0:
            raise GarminProviderError(GarminErrorCategory.SCHEMA_CHANGED, retryable=False)

        def download(client: Any) -> bytes:
            return cast(
                bytes,
                client.download_activity(
                    external_activity_id,
                    client.ActivityDownloadFormat.ORIGINAL,
                ),
            )

        content = await self._call(user_id, download)
        content_type = "application/zip" if content.startswith(b"PK") else "application/vnd.ant.fit"
        return GarminActivityFileDTO(content=content, content_type=content_type)

    async def create_workout(
        self, user_id: UserId, payload: GarminWorkoutDTO
    ) -> ExternalWorkoutResult:
        try:
            raw = await self._call(user_id, lambda client: client.upload_workout(payload.payload))
            if not isinstance(raw, Mapping):
                raise GarminProviderError(
                    GarminErrorCategory.SCHEMA_CHANGED,
                    retryable=False,
                    outcome_ambiguous=True,
                )
            external_id = raw.get("workoutId", raw.get("id"))
            if not isinstance(external_id, str | int):
                raise GarminProviderError(
                    GarminErrorCategory.SCHEMA_CHANGED,
                    retryable=False,
                    outcome_ambiguous=True,
                )
            return ExternalWorkoutResult(str(external_id), cast(JsonObject, _json_safe(raw)))
        except GarminProviderError as exc:
            if exc.category in {GarminErrorCategory.NETWORK, GarminErrorCategory.UNKNOWN}:
                raise GarminProviderError(
                    exc.category,
                    retryable=exc.retryable,
                    retry_after_seconds=exc.retry_after_seconds,
                    outcome_ambiguous=True,
                ) from exc
            raise

    async def schedule_workout(
        self, user_id: UserId, external_workout_id: str, scheduled_date: date
    ) -> ExternalScheduleResult:
        try:
            raw = await self._call(
                user_id,
                lambda client: client.schedule_workout(
                    external_workout_id, scheduled_date.isoformat()
                ),
            )
            if not isinstance(raw, Mapping):
                raise GarminProviderError(
                    GarminErrorCategory.SCHEMA_CHANGED,
                    retryable=False,
                    outcome_ambiguous=True,
                )
            external_schedule_id = raw.get("scheduledWorkoutId", raw.get("id"))
            if not isinstance(external_schedule_id, str | int):
                external_schedule_id = None
            return ExternalScheduleResult(
                str(external_schedule_id) if external_schedule_id is not None else None,
                scheduled_date,
                cast(JsonObject, _json_safe(raw)),
            )
        except GarminProviderError as exc:
            if exc.category in {GarminErrorCategory.NETWORK, GarminErrorCategory.UNKNOWN}:
                raise GarminProviderError(
                    exc.category,
                    retryable=exc.retryable,
                    retry_after_seconds=exc.retry_after_seconds,
                    outcome_ambiguous=True,
                ) from exc
            raise

    async def update_workout(
        self, user_id: UserId, external_workout_id: str, payload: GarminWorkoutDTO
    ) -> ExternalWorkoutResult:
        try:
            raw = await self._call(
                user_id,
                lambda client: client.update_workout(external_workout_id, payload.payload),
            )
            if not isinstance(raw, Mapping):
                raise GarminProviderError(
                    GarminErrorCategory.SCHEMA_CHANGED,
                    retryable=False,
                    outcome_ambiguous=True,
                )
            external_id = raw.get("workoutId", raw.get("id", external_workout_id))
            return ExternalWorkoutResult(str(external_id), cast(JsonObject, _json_safe(raw)))
        except GarminProviderError as exc:
            if exc.category in {GarminErrorCategory.NETWORK, GarminErrorCategory.UNKNOWN}:
                raise GarminProviderError(
                    exc.category,
                    retryable=exc.retryable,
                    retry_after_seconds=exc.retry_after_seconds,
                    outcome_ambiguous=True,
                ) from exc
            raise

    async def unschedule_workout(self, user_id: UserId, external_schedule_id: str) -> None:
        try:
            await self._call(
                user_id,
                lambda client: client.unschedule_workout(external_schedule_id),
            )
        except GarminProviderError as exc:
            if exc.category is GarminErrorCategory.NOT_FOUND:
                return
            raise

    async def delete_workout(self, user_id: UserId, external_workout_id: str) -> None:
        try:
            await self._call(
                user_id,
                lambda client: client.delete_workout(external_workout_id),
            )
        except GarminProviderError as exc:
            if exc.category is GarminErrorCategory.NOT_FOUND:
                return
            if exc.category in {GarminErrorCategory.NETWORK, GarminErrorCategory.UNKNOWN}:
                raise GarminProviderError(
                    exc.category,
                    retryable=True,
                    retry_after_seconds=exc.retry_after_seconds,
                    outcome_ambiguous=True,
                ) from exc
            raise

    async def find_workout_by_source_hash(
        self, user_id: UserId, source_revision_hash: str
    ) -> ExternalWorkoutResult | None:
        marker = f"[swim-coach:{source_revision_hash}]"
        raw_items = await self._call(user_id, lambda client: client.get_workouts(0, 100))
        for raw in raw_items:
            if not isinstance(raw, Mapping) or marker not in str(raw.get("description", "")):
                continue
            external_id = raw.get("workoutId", raw.get("id"))
            if isinstance(external_id, str | int):
                return ExternalWorkoutResult(str(external_id), cast(JsonObject, _json_safe(raw)))
        return None

    async def find_schedule(
        self, user_id: UserId, external_workout_id: str, scheduled_date: date
    ) -> ExternalScheduleResult | None:
        raw = await self._call(
            user_id,
            lambda client: client.get_scheduled_workouts(scheduled_date.year, scheduled_date.month),
        )
        for item in _walk_mappings(raw):
            workout_id = item.get(
                "workoutId",
                item.get("workout", {}).get("workoutId")
                if isinstance(item.get("workout"), Mapping)
                else None,
            )
            item_date = item.get("date", item.get("calendarDate"))
            if (
                str(workout_id) != external_workout_id
                or str(item_date)[:10] != scheduled_date.isoformat()
            ):
                continue
            schedule_id = item.get("scheduledWorkoutId", item.get("id"))
            return ExternalScheduleResult(
                str(schedule_id) if isinstance(schedule_id, str | int) else None,
                scheduled_date,
                cast(JsonObject, _json_safe(item)),
            )
        return None


def _walk_mappings(value: object) -> list[Mapping[str, Any]]:
    result: list[Mapping[str, Any]] = []
    if isinstance(value, Mapping):
        result.append(value)
        for child in value.values():
            result.extend(_walk_mappings(child))
    elif isinstance(value, list | tuple):
        for child in value:
            result.extend(_walk_mappings(child))
    return result
