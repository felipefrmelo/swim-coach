"""Garmin provider port and library-independent integration DTOs."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from swim_coach.domain.shared.types import JsonObject
from swim_coach.domain.shared.value_objects import UserId


class GarminErrorCategory(StrEnum):
    AUTH_REQUIRED = "GARMIN_AUTH_REQUIRED"
    RATE_LIMITED = "GARMIN_RATE_LIMITED"
    NETWORK = "GARMIN_NETWORK_ERROR"
    NOT_FOUND = "GARMIN_NOT_FOUND"
    SCHEMA_CHANGED = "GARMIN_SCHEMA_CHANGED"
    UNKNOWN = "GARMIN_UNKNOWN_ERROR"


class GarminProviderError(Exception):
    """Sanitized provider failure safe for retry policy and structured logs."""

    def __init__(
        self,
        category: GarminErrorCategory,
        *,
        retryable: bool,
        retry_after_seconds: int | None = None,
    ) -> None:
        super().__init__(category.value)
        self.category = category
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds


@dataclass(frozen=True, slots=True)
class GarminProviderCapabilities:
    activity_read: bool = True
    device_read: bool = True
    file_read: bool = False
    workout_write: bool = False
    observed_version: str = "unknown"


@dataclass(frozen=True, slots=True)
class ProviderConnectionStatus:
    active: bool
    reauth_required: bool
    account_label_masked: str


@dataclass(frozen=True, slots=True)
class GarminDeviceDTO:
    external_id: str
    model: str
    name: str
    serial_hash: str | None = None
    capabilities: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class GarminActivitySummaryDTO:
    external_id: str
    name: str
    sport: str
    subtype: str
    start_time_utc: datetime
    timezone: str
    distance_m: int
    elapsed_seconds: Decimal
    timer_seconds: Decimal
    moving_seconds: Decimal
    provider_updated_at: datetime | None
    pool_length_m: int | None = None
    length_count: int | None = None
    calories: int | None = None
    avg_hr: int | None = None
    max_hr: int | None = None
    avg_pace_seconds_per_100m: Decimal | None = None
    avg_stroke_rate: Decimal | None = None
    avg_strokes_per_length: Decimal | None = None
    avg_swolf: Decimal | None = None
    raw_safe: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ActivityFilter:
    started_after: datetime | None
    page_size: int = 20
    pool_swim_only: bool = True

    def __post_init__(self) -> None:
        if not 1 <= self.page_size <= 100:
            raise ValueError("page size must be between 1 and 100")


@dataclass(frozen=True, slots=True)
class ProviderPage:
    items: tuple[GarminActivitySummaryDTO, ...]
    next_cursor: str | None


class GarminProvider(Protocol):
    @property
    def capabilities(self) -> GarminProviderCapabilities: ...

    async def validate_connection(self, user_id: UserId) -> ProviderConnectionStatus: ...
    async def list_devices(self, user_id: UserId) -> tuple[GarminDeviceDTO, ...]: ...
    async def list_activities(
        self,
        user_id: UserId,
        cursor: str | None,
        filters: ActivityFilter,
    ) -> ProviderPage: ...


class GarminCredentialBootstrap(Protocol):
    @property
    def observed_version(self) -> str: ...

    async def authenticate(
        self,
        email: str,
        password: str,
        prompt_mfa: Callable[[], str],
    ) -> bytes: ...
