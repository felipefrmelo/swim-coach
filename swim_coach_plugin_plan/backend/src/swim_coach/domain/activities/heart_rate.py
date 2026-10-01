"""Bounded heart-rate facts; missing measurements never become zero."""

from decimal import Decimal, InvalidOperation
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field

from swim_coach.domain.shared.types import JsonObject


def valid_bpm(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    # 255 is the FIT uint8 invalid sentinel. Do not impose age-based limits.
    if not number.is_finite() or number != number.to_integral_value():
        return None
    return int(number) if 0 < number < 255 else None


class HeartRateZone(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    zone_index: int = Field(ge=0, le=15)
    duration_s: str
    percent_of_zone_time: str
    high_boundary_bpm: int | None = None


class HeartRateFacts(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    avg_bpm: int | None = Field(default=None, ge=1, le=254)
    max_bpm: int | None = Field(default=None, ge=1, le=254)
    source: Literal["FIT_SESSION", "GARMIN_SUMMARY"] | None = None
    zones: tuple[HeartRateZone, ...] = ()
    zones_source: Literal["FIT_SESSION", "FIT_TIME_IN_ZONE"] | None = None
    zone_time_s: str | None = None
    zone_time_basis: Literal["GARMIN_REPORTED_ZONE_TIME"] | None = None
    warnings: tuple[str, ...] = ()

    def as_json(self) -> JsonObject:
        return cast(JsonObject, self.model_dump(mode="json"))
