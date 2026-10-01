"""Project FIT session HR and reported zone times without reconstructing samples."""

from collections.abc import Mapping, Sequence
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Literal

from swim_coach.domain.activities.heart_rate import HeartRateFacts, HeartRateZone, valid_bpm


def fit_heart_rate(session: Mapping[str, Any], decoded: Mapping[str, Any]) -> HeartRateFacts:
    warnings: list[str] = []
    avg = valid_bpm(session.get("avg_heart_rate"))
    maximum = valid_bpm(session.get("max_heart_rate"))
    if avg is not None and maximum is not None and avg > maximum:
        avg = maximum = None
        warnings.append("HR_AVERAGE_EXCEEDS_MAXIMUM")
    zone_record = session
    zone_source: Literal["FIT_SESSION", "FIT_TIME_IN_ZONE"] = "FIT_SESSION"
    if session.get("time_in_hr_zone") is None:
        # Newer devices can put session zones in a referenced time_in_zone message.
        candidates = [
            item
            for item in decoded.get("time_in_zone_mesgs", [])
            if isinstance(item, Mapping)
            and item.get("reference_mesg") in ("session", 18)
            and item.get("reference_index") == session.get("message_index", 0)
        ]
        if len(candidates) == 1:
            zone_record = candidates[0]
            zone_source = "FIT_TIME_IN_ZONE"
    raw_times = zone_record.get("time_in_hr_zone")
    zones: tuple[HeartRateZone, ...] = ()
    total: Decimal | None = None
    if isinstance(raw_times, Sequence) and not isinstance(raw_times, (str, bytes)):
        try:
            times = [Decimal(str(value)) for value in raw_times]
            valid = 0 < len(times) <= 16 and all(
                value.is_finite() and 0 <= value < Decimal("4294967.295") for value in times
            )
            total = sum(times, Decimal(0)) if valid else None
        except (InvalidOperation, ValueError):
            times, total = [], None
        if total is not None and total > 0:
            boundaries = zone_record.get("hr_zone_high_boundary", [])
            if not isinstance(boundaries, Sequence) or isinstance(boundaries, (str, bytes)):
                boundaries = []
            # Preserve FIT indices. No assumption about Z1-Z5 or age-derived limits.
            zones = tuple(
                HeartRateZone(
                    zone_index=index,
                    duration_s=format(value, "f"),
                    percent_of_zone_time=format(
                        (value / total * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
                        "f",
                    ),
                    high_boundary_bpm=(
                        valid_bpm(boundaries[index]) if index < len(boundaries) else None
                    ),
                )
                for index, value in enumerate(times)
            )
            if any(zone.high_boundary_bpm is None for zone in zones):
                warnings.append("HR_ZONE_BOUNDARIES_UNAVAILABLE")
            timer = session.get("total_timer_time")
            try:
                timer_seconds = Decimal(str(timer))
                if timer_seconds.is_finite() and total > timer_seconds + Decimal(1):
                    warnings.append("HR_ZONE_TIME_EXCEEDS_TIMER")
            except (InvalidOperation, ValueError):
                pass
        else:
            warnings.append("HR_ZONE_TIMES_INVALID_OR_EMPTY")
    if not zones:
        warnings.append("HR_ZONES_UNAVAILABLE")
    if avg is None and maximum is None:
        warnings.append("HR_SESSION_UNAVAILABLE")
    return HeartRateFacts(
        avg_bpm=avg,
        max_bpm=maximum,
        source="FIT_SESSION" if avg is not None or maximum is not None else None,
        zones=zones,
        zones_source=zone_source if zones else None,
        zone_time_s=format(total, "f") if zones and total is not None else None,
        zone_time_basis="GARMIN_REPORTED_ZONE_TIME" if zones else None,
        warnings=tuple(warnings),
    )
