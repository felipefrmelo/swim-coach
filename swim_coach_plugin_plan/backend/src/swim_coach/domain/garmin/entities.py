"""User-scoped Garmin connection and incremental activity import records."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from swim_coach.domain.identity.entities import utc_now
from swim_coach.domain.shared.errors import DomainValidationError
from swim_coach.domain.shared.types import JsonObject
from swim_coach.domain.shared.value_objects import (
    Distance,
    Duration,
    EncryptedSecret,
    EntityId,
    PoolLength,
    UserId,
)


class GarminConnectionStatus(StrEnum):
    DISCONNECTED = "disconnected"
    ACTIVE = "active"
    DEGRADED = "degraded"
    REAUTH_REQUIRED = "reauth_required"
    DISABLED = "disabled"


class SyncRunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ActivityImportStatus(StrEnum):
    CREATED = "created"
    UPDATED = "updated"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass(slots=True)
class GarminConnection:
    user_id: UserId
    status: GarminConnectionStatus
    account_label_masked: str
    encrypted_token: EncryptedSecret | None
    provider_library_version: str
    authenticated_at: datetime | None = None
    last_refresh_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error_code: str | None = None
    last_error_message_redacted: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    version: int = 1

    def __post_init__(self) -> None:
        if not self.account_label_masked.strip() or "*" not in self.account_label_masked:
            raise DomainValidationError("Garmin account label must be masked")
        if self.status is GarminConnectionStatus.ACTIVE and self.encrypted_token is None:
            raise DomainValidationError("active Garmin connection requires an encrypted token")
        if self.version < 1:
            raise DomainValidationError("Garmin connection version must be positive")

    def mark_success(self, *, refreshed: bool = False) -> None:
        now = utc_now()
        self.status = GarminConnectionStatus.ACTIVE
        self.last_success_at = now
        if refreshed:
            self.last_refresh_at = now
        self.last_error_code = None
        self.last_error_message_redacted = None
        self.updated_at = now
        self.version += 1

    def mark_error(self, code: str, *, reauth_required: bool) -> None:
        self.status = (
            GarminConnectionStatus.REAUTH_REQUIRED
            if reauth_required
            else GarminConnectionStatus.DEGRADED
        )
        self.last_error_code = code
        self.last_error_message_redacted = "Garmin provider request failed"
        self.updated_at = utc_now()
        self.version += 1

    def disconnect(self) -> None:
        self.status = GarminConnectionStatus.DISCONNECTED
        self.encrypted_token = None
        self.last_error_code = None
        self.last_error_message_redacted = None
        self.updated_at = utc_now()
        self.version += 1


@dataclass(slots=True)
class SyncCursor:
    id: EntityId
    user_id: UserId
    provider: str
    entity_type: str
    cursor: JsonObject = field(default_factory=dict)
    watermark_at: datetime | None = None
    last_success_at: datetime | None = None
    overlap_seconds: int = 172_800
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    version: int = 1

    def __post_init__(self) -> None:
        if not self.provider.strip() or not self.entity_type.strip():
            raise DomainValidationError("sync cursor provider and entity type are required")
        if self.overlap_seconds < 0:
            raise DomainValidationError("sync cursor overlap cannot be negative")


@dataclass(slots=True)
class SyncRun:
    id: EntityId
    user_id: UserId
    provider: str
    sync_type: str
    trigger: str
    status: SyncRunStatus = SyncRunStatus.RUNNING
    listed: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    cursor_before: JsonObject = field(default_factory=dict)
    cursor_after: JsonObject = field(default_factory=dict)
    error: JsonObject | None = None
    started_at: datetime = field(default_factory=utc_now)
    finished_at: datetime | None = None
    version: int = 1

    def __post_init__(self) -> None:
        if not self.provider.strip() or not self.sync_type.strip() or not self.trigger.strip():
            raise DomainValidationError("sync run provider, type and trigger are required")
        if min(self.listed, self.created, self.updated, self.skipped, self.failed) < 0:
            raise DomainValidationError("sync run counters cannot be negative")

    def finish(self, cursor_after: JsonObject) -> None:
        self.cursor_after = cursor_after
        self.status = SyncRunStatus.PARTIAL if self.failed else SyncRunStatus.SUCCEEDED
        self.finished_at = utc_now()
        self.version += 1

    def fail(self, code: str, *, retryable: bool) -> None:
        self.status = SyncRunStatus.FAILED
        self.error = {"code": code, "retryable": retryable}
        self.finished_at = utc_now()
        self.version += 1

    def cancel(self) -> None:
        self.status = SyncRunStatus.CANCELLED
        self.error = {"code": "SYNC_CANCELLED", "retryable": True}
        self.finished_at = utc_now()
        self.version += 1


@dataclass(slots=True)
class RawProviderPayload:
    id: EntityId
    user_id: UserId
    provider: str
    entity_type: str
    external_id: str
    content_type: str
    payload: JsonObject
    checksum: str
    provider_updated_at: datetime | None
    received_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (self.provider, self.entity_type, self.external_id, self.content_type)
        ):
            raise DomainValidationError("raw provider payload identity fields are required")
        if len(self.checksum) != 64:
            raise DomainValidationError("raw provider payload requires a SHA-256 checksum")


@dataclass(slots=True)
class Activity:
    id: EntityId
    user_id: UserId
    provider: str
    external_activity_id: str
    name: str
    sport: str
    subtype: str
    start_time_utc: datetime
    timezone: str
    distance: Distance
    elapsed: Duration
    timer: Duration
    moving: Duration
    summary_checksum: str
    raw_summary_id: EntityId
    source_updated_at: datetime | None = None
    pool_length: PoolLength | None = None
    length_count: int | None = None
    calories: int | None = None
    avg_hr: int | None = None
    max_hr: int | None = None
    avg_pace_seconds_per_100m: Decimal | None = None
    avg_stroke_rate: Decimal | None = None
    avg_strokes_per_length: Decimal | None = None
    avg_swolf: Decimal | None = None
    normalization_version: str | None = None
    raw_fit_id: EntityId | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    version: int = 1

    def __post_init__(self) -> None:
        if not self.provider.strip() or not self.external_activity_id.strip():
            raise DomainValidationError("activity provider and external id are required")
        utc_offset = self.start_time_utc.utcoffset()
        if (
            self.start_time_utc.tzinfo is None
            or utc_offset is None
            or utc_offset.total_seconds() != 0
        ):
            raise DomainValidationError("activity start time must use UTC")
        if len(self.summary_checksum) != 64:
            raise DomainValidationError("activity summary requires a SHA-256 checksum")
        if self.length_count is not None and self.length_count < 0:
            raise DomainValidationError("activity length count cannot be negative")


@dataclass(slots=True)
class ActivityImport:
    id: EntityId
    user_id: UserId
    sync_run_id: EntityId
    external_activity_id: str
    status: ActivityImportStatus
    checksum: str
    activity_id: EntityId | None = None
    error_code: str | None = None
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not self.external_activity_id.strip() or len(self.checksum) != 64:
            raise DomainValidationError("activity import identity and checksum are required")
        if self.status is ActivityImportStatus.FAILED and not self.error_code:
            raise DomainValidationError("failed activity import requires an error code")
