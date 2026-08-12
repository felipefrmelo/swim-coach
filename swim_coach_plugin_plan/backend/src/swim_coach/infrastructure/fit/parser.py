"""Versioned swimming normalizer backed by the official Garmin FIT Python SDK."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from garmin_fit_sdk import Decoder, Stream  # type: ignore[import-untyped]
from garmin_fit_sdk import __version__ as fit_sdk_version

from swim_coach.domain.activities import (
    ActivityInterval,
    ActivityLap,
    ActivityLength,
    ActivityNormalization,
    DataQuality,
    NormalizedActivity,
    pace_seconds_per_100m,
)
from swim_coach.domain.shared.errors import DomainError
from swim_coach.domain.shared.value_objects import EntityId, UserId


def _decimal(value: object, default: Decimal = Decimal(0)) -> Decimal:
    if value is None:
        return default
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise DomainError("FIT_PARSE_FAILED", "FIT contains an invalid numeric field.") from exc
    if not result.is_finite() or result < 0:
        raise DomainError("FIT_PARSE_FAILED", "FIT contains an invalid numeric field.")
    return result


def _integer(value: object) -> int | None:
    return None if value is None else int(_decimal(value))


def _messages(decoded: Mapping[str, Any], name: str) -> tuple[Mapping[str, Any], ...]:
    value = decoded.get(f"{name}_mesgs", ())
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, Mapping))


def _timestamp(value: object) -> datetime | None:
    return value if isinstance(value, datetime) else None


def _offset(value: object, origin: datetime | None, fallback: Decimal) -> Decimal:
    instant = _timestamp(value)
    if instant is None or origin is None:
        return fallback
    return max(Decimal(0), Decimal(str((instant - origin).total_seconds())))


class GarminFitActivityParser:
    NORMALIZER_VERSION = "1.0.0"

    def __init__(self, *, max_size_bytes: int = 50 * 1024 * 1024) -> None:
        self._max_size_bytes = max_size_bytes

    @property
    def parser_version(self) -> str:
        return f"garmin-fit-sdk:{fit_sdk_version}|swim-coach:{self.NORMALIZER_VERSION}"

    @property
    def profile_version(self) -> str:
        return str(fit_sdk_version)

    def normalize(
        self,
        data: bytes,
        *,
        user_id: UserId,
        activity_id: EntityId,
        artifact_id: EntityId,
        input_checksum: str,
        fallback_pool_length_m: int,
    ) -> NormalizedActivity:
        if not data or len(data) > self._max_size_bytes:
            raise DomainError("FIT_FILE_INVALID", "FIT file is empty or exceeds the size limit.")
        integrity_decoder = Decoder(Stream.from_byte_array(bytearray(data)))
        if not integrity_decoder.is_fit() or not integrity_decoder.check_integrity():
            raise DomainError("FIT_PARSE_FAILED", "FIT integrity validation failed.")
        decoder = Decoder(Stream.from_byte_array(bytearray(data)))
        decoded, errors = decoder.read()
        if errors:
            raise DomainError("FIT_PARSE_FAILED", "FIT decoding failed.")
        if not isinstance(decoded, Mapping):
            raise DomainError("FIT_PARSE_FAILED", "FIT message structure is invalid.")
        return self.normalize_messages(
            decoded,
            user_id=user_id,
            activity_id=activity_id,
            artifact_id=artifact_id,
            input_checksum=input_checksum,
            fallback_pool_length_m=fallback_pool_length_m,
        )

    def normalize_messages(
        self,
        decoded: Mapping[str, Any],
        *,
        user_id: UserId,
        activity_id: EntityId,
        artifact_id: EntityId,
        input_checksum: str,
        fallback_pool_length_m: int,
    ) -> NormalizedActivity:
        sessions = _messages(decoded, "session")
        raw_laps = _messages(decoded, "lap")
        has_source_laps = bool(raw_laps)
        raw_lengths = _messages(decoded, "length")
        records = _messages(decoded, "record")
        session = sessions[0] if sessions else {}
        pool_length_m = _integer(session.get("pool_length")) or fallback_pool_length_m
        if pool_length_m <= 0:
            raise DomainError("FIT_PARSE_FAILED", "FIT pool length is missing or invalid.")
        active_raw_lengths = tuple(
            item for item in raw_lengths if str(item.get("length_type", "active")) != "idle"
        )
        calculated_distance = len(active_raw_lengths) * pool_length_m
        explicit_distance = _integer(session.get("total_distance")) or 0
        warnings: list[str] = []
        if calculated_distance and explicit_distance:
            if abs(calculated_distance - explicit_distance) <= pool_length_m:
                distance_m = explicit_distance
            else:
                distance_m = calculated_distance
                warnings.append("SESSION_LENGTH_DISTANCE_MISMATCH")
        else:
            distance_m = explicit_distance or calculated_distance
        if not active_raw_lengths:
            warnings.append("LENGTH_MESSAGES_UNAVAILABLE")
        elapsed_seconds = _decimal(session.get("total_elapsed_time"))
        timer_seconds = _decimal(session.get("total_timer_time"), elapsed_seconds)
        moving_seconds = timer_seconds
        origin = _timestamp(session.get("start_time"))
        normalization_id = EntityId.new()
        laps: list[ActivityLap] = []
        intervals: list[ActivityInterval] = []
        lengths: list[ActivityLength] = []
        if not raw_laps:
            raw_laps = (
                {
                    "message_index": 0,
                    "start_time": origin,
                    "total_elapsed_time": elapsed_seconds,
                    "total_timer_time": timer_seconds,
                    "total_distance": distance_m,
                    "swim_stroke": session.get("swim_stroke"),
                },
            )
            warnings.append("LAP_MESSAGES_SYNTHESIZED")
        length_position = 0
        cumulative_offset = Decimal(0)
        for lap_position, raw_lap in enumerate(raw_laps):
            lap_elapsed = _decimal(raw_lap.get("total_elapsed_time"))
            lap_timer = _decimal(raw_lap.get("total_timer_time"), lap_elapsed)
            lap_distance = _integer(raw_lap.get("total_distance")) or 0
            if lap_distance <= 0 and len(raw_laps) == 1:
                lap_distance = distance_m
            lap_offset = _offset(raw_lap.get("start_time"), origin, cumulative_offset)
            lap = ActivityLap(
                id=EntityId.new(),
                normalization_id=normalization_id,
                lap_index=lap_position,
                start_offset_seconds=lap_offset,
                elapsed_seconds=lap_elapsed,
                timer_seconds=lap_timer,
                distance_m=lap_distance,
                avg_hr_bpm=_integer(raw_lap.get("avg_heart_rate")),
                max_hr_bpm=_integer(raw_lap.get("max_heart_rate")),
                stroke_type=(str(raw_lap["swim_stroke"]) if raw_lap.get("swim_stroke") else None),
            )
            laps.append(lap)
            interval_id = EntityId.new()
            lap_rest = max(Decimal(0), lap_elapsed - lap_timer)
            interval = ActivityInterval(
                id=interval_id,
                normalization_id=normalization_id,
                interval_index=lap_position,
                interval_type="work",
                start_offset_seconds=lap_offset,
                duration_seconds=lap_timer,
                rest_seconds=lap_rest,
                distance_m=lap_distance,
                pace_seconds_per_100m=pace_seconds_per_100m(lap_timer, lap_distance),
                avg_hr_bpm=lap.avg_hr_bpm,
                max_hr_bpm=lap.max_hr_bpm,
                stroke_type=lap.stroke_type,
                stroke_count=_integer(raw_lap.get("total_strokes")),
                stroke_rate=(
                    _decimal(raw_lap.get("avg_cadence"))
                    if raw_lap.get("avg_cadence") is not None
                    else None
                ),
                swolf=(
                    _decimal(raw_lap.get("avg_swolf"))
                    if raw_lap.get("avg_swolf") is not None
                    else None
                ),
                source={
                    "lap_message_index": _integer(raw_lap.get("message_index")) or lap_position
                },
            )
            intervals.append(interval)
            lap_end = lap_offset + lap_elapsed
            while length_position < len(active_raw_lengths):
                raw_length = active_raw_lengths[length_position]
                length_start = _offset(raw_length.get("start_time"), origin, lap_offset)
                if lap_position < len(raw_laps) - 1 and length_start >= lap_end:
                    break
                duration = _decimal(
                    raw_length.get("total_timer_time"),
                    _decimal(raw_length.get("total_elapsed_time")),
                )
                strokes = _integer(raw_length.get("total_strokes"))
                swolf_value = raw_length.get("avg_swolf")
                swolf = (
                    _decimal(swolf_value)
                    if swolf_value is not None
                    else (duration + Decimal(strokes) if strokes is not None else None)
                )
                lengths.append(
                    ActivityLength(
                        id=EntityId.new(),
                        normalization_id=normalization_id,
                        interval_id=interval_id,
                        length_index=len(lengths),
                        distance_m=pool_length_m,
                        duration_seconds=duration,
                        stroke_type=(
                            str(raw_length["swim_stroke"])
                            if raw_length.get("swim_stroke")
                            else lap.stroke_type
                        ),
                        stroke_count=strokes,
                        stroke_rate=(
                            _decimal(raw_length.get("avg_swimming_cadence"))
                            if raw_length.get("avg_swimming_cadence") is not None
                            else None
                        ),
                        swolf=swolf,
                        avg_hr_bpm=_integer(raw_length.get("avg_heart_rate")),
                    )
                )
                length_position += 1
            cumulative_offset = max(cumulative_offset, lap_end)
        completeness_parts = (
            bool(sessions),
            distance_m > 0,
            elapsed_seconds > 0,
            has_source_laps,
            bool(active_raw_lengths),
            any(item.get("heart_rate") is not None for item in records)
            or session.get("avg_heart_rate") is not None,
            any(item.stroke_count is not None for item in lengths),
            any(item.swolf is not None for item in lengths),
        )
        completeness = Decimal(sum(completeness_parts)) / Decimal(len(completeness_parts))
        quality = (
            DataQuality.COMPLETE
            if completeness >= Decimal("0.8")
            else DataQuality.PARTIAL
            if completeness >= Decimal("0.5")
            else DataQuality.POOR
        )
        normalization = ActivityNormalization(
            id=normalization_id,
            user_id=user_id,
            activity_id=activity_id,
            artifact_id=artifact_id,
            parser_version=self.parser_version,
            profile_version=self.profile_version,
            input_checksum=input_checksum,
            pool_length_m=pool_length_m,
            distance_m=distance_m,
            elapsed_seconds=elapsed_seconds,
            timer_seconds=timer_seconds,
            moving_seconds=moving_seconds,
            active_length_count=len(lengths),
            completeness=completeness.quantize(Decimal("0.001")),
            quality=quality,
            warnings=tuple(dict.fromkeys(warnings)),
        )
        return NormalizedActivity(normalization, tuple(laps), tuple(intervals), tuple(lengths))
