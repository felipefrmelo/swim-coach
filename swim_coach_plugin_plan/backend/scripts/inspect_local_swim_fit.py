"""Print a sanitized, local-only decoded FIT view for one owned activity."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from garmin_fit_sdk import Decoder, Stream  # type: ignore[import-untyped]

from swim_coach.bootstrap.container import build_services
from swim_coach.domain.shared.errors import DomainError, ResourceNotFoundError
from swim_coach.domain.shared.value_objects import EntityId, UserId
from swim_coach.settings import get_settings

SAFE_MESSAGE_FIELDS = {
    "session_mesgs": frozenset(
        {
            "sport",
            "sub_sport",
            "start_time",
            "total_elapsed_time",
            "total_timer_time",
            "total_moving_time",
            "total_distance",
            "avg_speed",
            "enhanced_avg_speed",
            "pool_length",
            "pool_length_unit",
            "num_active_lengths",
            "swim_stroke",
        }
    ),
    "lap_mesgs": frozenset(
        {
            "message_index",
            "first_length_index",
            "num_lengths",
            "start_time",
            "total_elapsed_time",
            "total_timer_time",
            "total_moving_time",
            "total_distance",
            "avg_speed",
            "enhanced_avg_speed",
            "swim_stroke",
            "total_strokes",
            "avg_cadence",
            "avg_swolf",
        }
    ),
    "length_mesgs": frozenset(
        {
            "message_index",
            "start_time",
            "length_type",
            "total_elapsed_time",
            "total_timer_time",
            "total_strokes",
            "avg_speed",
            "enhanced_avg_speed",
            "swim_stroke",
            "avg_swimming_cadence",
            "avg_swolf",
        }
    ),
    "workout_step_mesgs": frozenset(
        {
            "message_index",
            "duration_type",
            "duration_value",
            "target_type",
            "target_value",
            "custom_target_value_low",
            "custom_target_value_high",
            "intensity",
            "swim_stroke",
            "equipment",
        }
    ),
}

SAFE_SUMMARY_FIELDS = frozenset(
    {
        "activityType",
        "startTimeGMT",
        "startTimeLocal",
        "distance",
        "duration",
        "elapsedDuration",
        "movingDuration",
        "poolLength",
        "poolLengthUnit",
        "unitOfPoolLength",
        "numberOfActiveLengths",
        "averagePace",
        "averageSwimCadenceInStrokesPerMinute",
        "avgStrokes",
        "avgSwolf",
    }
)
_MAX_SAFE_LIST_ITEMS = 100
_UNSUPPORTED_REDACTION = "<unsupported-redacted>"


def _safe_value(value: object, *, include_timestamps: bool) -> Any:
    # Nested maps are not part of the reviewed FIT projection. Deny them by
    # default instead of recursively leaking future SDK fields.
    if isinstance(value, Mapping):
        return {}
    if isinstance(value, list | tuple):
        return [
            _safe_value(item, include_timestamps=include_timestamps)
            for item in value[:_MAX_SAFE_LIST_ITEMS]
        ]
    if isinstance(value, datetime | date):
        return value.isoformat() if include_timestamps else "<timestamp-redacted>"
    if isinstance(value, Decimal):
        return format(value, "f")
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Enum):
        primitive = value.value
        return (
            primitive if isinstance(primitive, str | int | float | bool) else _UNSUPPORTED_REDACTION
        )
    return _UNSUPPORTED_REDACTION


def _safe_messages(
    value: object, *, message_name: str, include_timestamps: bool
) -> list[dict[str, Any]]:
    allowed = SAFE_MESSAGE_FIELDS.get(message_name)
    if allowed is None:
        return []
    if not isinstance(value, list | tuple):
        return []
    result: list[dict[str, Any]] = []
    for message in value:
        if not isinstance(message, Mapping):
            continue
        result.append(
            {
                str(key): (
                    "<timestamp-redacted>"
                    if str(key) == "start_time" and not include_timestamps
                    else _safe_value(item, include_timestamps=include_timestamps)
                )
                for key, item in message.items()
                if str(key) in allowed
            }
        )
    return result


def _safe_semantic_value(value: object) -> Any:
    """Serialize trusted Swim Coach semantic metadata, never external nested payloads."""

    if isinstance(value, Mapping):
        return {str(key): _safe_semantic_value(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_safe_semantic_value(item) for item in value[:_MAX_SAFE_LIST_ITEMS]]
    if isinstance(value, Decimal):
        return format(value, "f")
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Enum):
        primitive = value.value
        return (
            primitive if isinstance(primitive, str | int | float | bool) else _UNSUPPORTED_REDACTION
        )
    return _UNSUPPORTED_REDACTION


def _safe_summary(payload: Mapping[str, Any], *, include_timestamps: bool) -> dict[str, Any]:
    """Return only reviewed activity-list facts; identifiers and names stay private."""

    result: dict[str, Any] = {}
    for key, value in payload.items():
        name = str(key)
        if name not in SAFE_SUMMARY_FIELDS:
            continue
        if name in {"startTimeGMT", "startTimeLocal"} and not include_timestamps:
            result[name] = "<timestamp-redacted>"
        elif name == "activityType" and isinstance(value, Mapping):
            type_key = value.get("typeKey")
            result[name] = {"typeKey": str(type_key)} if type_key is not None else {}
        else:
            result[name] = _safe_value(value, include_timestamps=include_timestamps)
    semantics = payload.get("_swim_coach_semantics")
    if isinstance(semantics, Mapping):
        result["_swim_coach_semantics"] = {
            "provenance": _safe_semantic_value(semantics.get("provenance")),
            "warnings": _safe_value(
                semantics.get("warnings"), include_timestamps=include_timestamps
            ),
            "athlete_timezone": _safe_value(
                semantics.get("athlete_timezone"), include_timestamps=include_timestamps
            ),
            "expected_local_wall": (
                _safe_value(
                    semantics.get("expected_local_wall"),
                    include_timestamps=include_timestamps,
                )
                if include_timestamps
                else "<timestamp-redacted>"
            ),
        }
    return result


async def _read(
    user_id: UserId,
    activity_id: EntityId,
    *,
    include_timestamps: bool,
    require_fit: bool = False,
) -> dict[str, Any]:
    services = build_services(get_settings())
    try:
        async with services.uow_factory() as uow:
            activity = await uow.activities.get(user_id, activity_id)
            artifacts = await uow.activity_data.list_artifacts(user_id)
            raw_summary = (
                await uow.raw_provider_payloads.get(user_id, activity.raw_summary_id)
                if activity is not None
                else None
            )
        if activity is None:
            raise ResourceNotFoundError("activity")
        matches = [
            item
            for item in artifacts
            if item.activity_id == activity_id and item.artifact_type == "fit"
        ]
        if not matches:
            if require_fit:
                raise DomainError("FIT_FILE_UNAVAILABLE", "No local FIT artifact is available.")
            return {
                "activity_id": str(activity_id),
                "summary_checksum": activity.summary_checksum,
                "summary": (
                    _safe_summary(raw_summary.payload, include_timestamps=include_timestamps)
                    if raw_summary is not None
                    else None
                ),
                "fit_status": "unavailable",
                "artifact_checksum": None,
                "messages": {},
            }
        artifact = max(matches, key=lambda item: item.created_at)
        data = await services.artifact_storage.get(artifact.storage_key)
        if hashlib.sha256(data).hexdigest() != artifact.checksum:
            raise DomainError(
                "ARTIFACT_CHECKSUM_MISMATCH",
                "The local FIT checksum did not match its immutable metadata.",
            )
        integrity = Decoder(Stream.from_byte_array(bytearray(data)))
        if not integrity.is_fit() or not integrity.check_integrity():
            raise DomainError("FIT_PARSE_FAILED", "The local FIT failed integrity checks.")
        decoded, errors = Decoder(Stream.from_byte_array(bytearray(data))).read()
        if errors or not isinstance(decoded, Mapping):
            raise DomainError("FIT_PARSE_FAILED", "The local FIT could not be decoded.")
        return {
            "activity_id": str(activity_id),
            "summary_checksum": activity.summary_checksum,
            "summary": (
                _safe_summary(raw_summary.payload, include_timestamps=include_timestamps)
                if raw_summary is not None
                else None
            ),
            "artifact_checksum": artifact.checksum,
            "fit_status": "available",
            "messages": {
                name: _safe_messages(
                    decoded.get(name, []),
                    message_name=name,
                    include_timestamps=include_timestamps,
                )
                for name in SAFE_MESSAGE_FIELDS
                if name in decoded
            },
        }
    finally:
        await services.database.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--activity-id", required=True)
    parser.add_argument("--include-timestamps", action="store_true")
    parser.add_argument("--require-fit", action="store_true")
    args = parser.parse_args()
    payload = asyncio.run(
        _read(
            UserId.parse(args.user_id),
            EntityId.parse(args.activity_id),
            include_timestamps=args.include_timestamps,
            require_fit=args.require_fit,
        )
    )
    print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    main()
