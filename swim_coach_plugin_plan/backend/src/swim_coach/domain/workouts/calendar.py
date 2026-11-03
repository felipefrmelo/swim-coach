"""Local calendar resolution; language interpretation stays with the coach."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, model_validator

from swim_coach.domain.shared.errors import DomainError

Weekday = Literal["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"]
WEEKDAYS = ("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY")


class CalendarRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    period: Literal["TODAY", "TOMORROW", "THIS_WEEK", "NEXT_WEEK", "NEXT_OCCURRENCE", "ABSOLUTE"]
    weekday: Weekday | None = None
    local_date: date | None = None

    @model_validator(mode="after")
    def validate_request(self) -> CalendarRequest:
        if self.period in {"THIS_WEEK", "NEXT_WEEK", "NEXT_OCCURRENCE"} and self.weekday is None:
            raise ValueError("weekday is required for weekly calendar requests")
        if (self.period == "ABSOLUTE") != (self.local_date is not None):
            raise ValueError("local_date is required only for ABSOLUTE")
        return self


def resolve_calendar(request: CalendarRequest, *, reference: datetime, timezone: str) -> date:
    if reference.tzinfo is None:
        raise DomainError("VALIDATION_FAILED", "reference must include a timezone offset.")
    try:
        today = reference.astimezone(ZoneInfo(timezone)).date()
    except ZoneInfoNotFoundError as exc:
        raise DomainError("VALIDATION_FAILED", "Use a valid IANA timezone.") from exc
    if request.period == "ABSOLUTE":
        assert request.local_date is not None  # noqa: S101 - validated model invariant
        result = request.local_date
    elif request.period in {"TODAY", "TOMORROW"}:
        result = today + timedelta(days=request.period == "TOMORROW")
    else:
        index = WEEKDAYS.index(str(request.weekday))
        if request.period == "NEXT_OCCURRENCE":
            result = today + timedelta(days=(index - today.weekday()) % 7 or 7)
        else:
            result = (
                today
                - timedelta(days=today.weekday())
                + timedelta(days=index + (7 if request.period == "NEXT_WEEK" else 0))
            )
    if request.weekday and result.weekday() != WEEKDAYS.index(request.weekday):
        raise DomainError("CALENDAR_WEEKDAY_MISMATCH", "The absolute date and weekday disagree.")
    return result


def local_instant(day: date, start: time, timezone: str) -> datetime:
    """Reject nonexistent and ambiguous wall times instead of silently shifting them."""
    zone = ZoneInfo(timezone)
    wall = datetime.combine(day, start)
    candidates = [wall.replace(tzinfo=zone, fold=fold) for fold in (0, 1)]
    valid = [
        d for d in candidates if d.astimezone(UTC).astimezone(zone).replace(tzinfo=None) == wall
    ]
    if not valid or len({d.utcoffset() for d in valid}) != 1:
        raise DomainError(
            "CALENDAR_TIME_AMBIGUOUS",
            "Choose an unambiguous local time outside the DST transition.",
        )
    return valid[0]
