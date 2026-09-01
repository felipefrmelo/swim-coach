"""Canonical v2 swimming normalizer backed by the Garmin FIT Python SDK.

The SDK applies the FIT profile scale before returning values: pool length and
distance are metres, durations are seconds, and speeds are metres per second.
Garmin speed-derived pace is preserved separately from Swim Coach paces.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from garmin_fit_sdk import Decoder, Stream  # type: ignore[import-untyped]
from garmin_fit_sdk import __version__ as fit_sdk_version

from swim_coach.domain.activities import (
    ActivityInterval,
    ActivityLap,
    ActivityLength,
    ActivityNormalization,
    DataQuality,
    IntervalType,
    LengthType,
    NormalizedActivity,
    ProvenanceSource,
)
from swim_coach.domain.shared.errors import DomainError
from swim_coach.domain.shared.types import JsonObject
from swim_coach.domain.shared.value_objects import EntityId, UserId

ZERO = Decimal(0)
MILLISECOND = Decimal("0.001")
RPE_TENTH = Decimal("0.1")


def _milliseconds(value: Decimal) -> Decimal:
    return value.quantize(MILLISECOND, rounding=ROUND_HALF_UP)


def _decimal(value: object, default: Decimal = ZERO) -> Decimal:
    if value is None:
        return default
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise DomainError("FIT_PARSE_FAILED", "FIT contains an invalid numeric field.") from exc
    if not result.is_finite() or result < 0:
        raise DomainError("FIT_PARSE_FAILED", "FIT contains an invalid numeric field.")
    return result


def _optional_decimal(value: object) -> Decimal | None:
    return None if value is None else _decimal(value)


def _integer(value: object) -> int | None:
    if value is None:
        return None
    result = _decimal(value)
    if result != result.to_integral_value():
        raise DomainError("FIT_PARSE_FAILED", "FIT contains a non-integral count field.")
    return int(result)


def _session_evaluation(
    session: Mapping[str, Any], warnings: list[str]
) -> tuple[Decimal | None, int | None]:
    """Normalize documented FIT session evaluation fields without guessing.

    FIT Profile 21.208 defines ``workout_rpe`` as the Borg CR10 value
    multiplied by ten and ``workout_feel`` as an integer 0-100 score.  Invalid
    decoded values remain recoverable from the immutable FIT artifact but are
    not promoted into canonical facts.
    """

    perceived_effort_rpe: Decimal | None = None
    raw_rpe = session.get("workout_rpe")
    if raw_rpe is not None:
        try:
            parsed_rpe = Decimal(str(raw_rpe))
        except (InvalidOperation, ValueError):
            parsed_rpe = Decimal("NaN")
        if (
            parsed_rpe.is_finite()
            and parsed_rpe == parsed_rpe.to_integral_value()
            and ZERO <= parsed_rpe <= Decimal(100)
        ):
            perceived_effort_rpe = (parsed_rpe / Decimal(10)).quantize(RPE_TENTH)
        else:
            warnings.append("SESSION_WORKOUT_RPE_INVALID")

    feeling_score: int | None = None
    raw_feel = session.get("workout_feel")
    if raw_feel is not None:
        try:
            parsed_feel = Decimal(str(raw_feel))
        except (InvalidOperation, ValueError):
            parsed_feel = Decimal("NaN")
        if (
            parsed_feel.is_finite()
            and parsed_feel == parsed_feel.to_integral_value()
            and ZERO <= parsed_feel <= Decimal(100)
        ):
            feeling_score = int(parsed_feel)
        else:
            warnings.append("SESSION_WORKOUT_FEEL_INVALID")
    return perceived_effort_rpe, feeling_score


def _whole_metres(value: object) -> int | None:
    """Return an exactly representable whole-metre FIT measurement.

    The current canonical/database contract stores metre quantities as integers.
    Rejecting legitimate fractional measurements explicitly is safer than
    truncating them and silently corrupting distance, pace and pool invariants.
    The immutable FIT remains available for reprocessing when fractional-metre
    support is added to the canonical contract.
    """

    if value is None:
        return None
    result = _decimal(value)
    if result != result.to_integral_value():
        raise DomainError(
            "FIT_DISTANCE_PRECISION_UNSUPPORTED",
            "FIT distance cannot be represented by the whole-metre canonical model.",
        )
    return int(result)


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
    return max(ZERO, Decimal(str((instant - origin).total_seconds())))


def _pace(duration_seconds: Decimal | None, distance_m: int) -> Decimal | None:
    if duration_seconds is None or distance_m <= 0:
        return None
    return (duration_seconds * Decimal(100) / Decimal(distance_m)).quantize(
        Decimal("0.001"), rounding=ROUND_HALF_UP
    )


def _reported_speed_and_equivalent_pace(
    message: Mapping[str, Any],
) -> tuple[Decimal | None, Decimal | None, str | None]:
    """Return the Garmin speed fact and the pace explicitly derived from it.

    The FIT SDK has already applied the profile scale, so these speed fields are
    metres per second.  Pace is not a second Garmin fact: it is Swim Coach's
    ``100 / speed`` derivation and therefore receives DERIVED provenance.
    """

    for raw_field in ("enhanced_avg_speed", "avg_speed", "average_speed"):
        speed = _optional_decimal(message.get(raw_field))
        if speed is not None:
            pace = (
                (Decimal(100) / speed).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
                if speed > 0
                else None
            )
            return speed, pace, raw_field
    return None, None, None


def _speed_interpretation(raw_field: str | None) -> str:
    # The FIT profile documents avg_speed/enhanced_avg_speed and their unit, but
    # not which swimming-time population Garmin used to calculate them.  The
    # sporting interpretation therefore remains inferred for every accepted
    # adapter spelling, including the profile-backed fields.
    del raw_field
    return "inferred"


def _speed_field_unit_semantics(raw_field: str | None) -> str:
    return "documented" if raw_field in {"enhanced_avg_speed", "avg_speed"} else "inferred"


def _fact(
    source: ProvenanceSource,
    *,
    raw_field: str | None = None,
    transformation: str | None = None,
    interpretation: str = "documented",
    field_unit_semantics: str | None = None,
    calculation_basis: str | None = None,
    input_calculation_basis: str | None = None,
) -> JsonObject:
    result: JsonObject = {"source": source.value, "interpretation": interpretation}
    if raw_field is not None:
        result["raw_field"] = raw_field
    if transformation is not None:
        result["transformation"] = transformation
    if field_unit_semantics is not None:
        result["field_unit_semantics"] = field_unit_semantics
    if calculation_basis is not None:
        result["calculation_basis"] = calculation_basis
    if input_calculation_basis is not None:
        result["input_calculation_basis"] = input_calculation_basis
    return result


def _duration_warnings(
    *,
    elapsed: Decimal,
    timer: Decimal,
    moving: Decimal | None,
    rest: Decimal | None = None,
    scope: str,
) -> list[str]:
    warnings: list[str] = []
    if timer > elapsed:
        warnings.append(f"{scope}_TIMER_EXCEEDS_ELAPSED")
    if moving is not None and moving > timer:
        warnings.append(f"{scope}_MOVING_EXCEEDS_TIMER")
    if rest is not None and rest > timer:
        warnings.append(f"{scope}_REST_EXCEEDS_TIMER")
    return warnings


def _stationary_duration(
    timer: Decimal,
    moving: Decimal | None,
    rest: Decimal | None,
    warnings: list[str],
    *,
    scope: str,
) -> Decimal | None:
    if moving is None or rest is None:
        return None
    result = timer - moving - rest
    if result < 0:
        warnings.append(f"{scope}_DURATION_DECOMPOSITION_INCONSISTENT")
        return None
    return _milliseconds(result)


def _pace_warning(
    pace_from_reported_speed: Decimal | None,
    timer_pace: Decimal | None,
    *,
    scope: str,
) -> str | None:
    if pace_from_reported_speed is None or timer_pace is None:
        return None
    tolerance = max(Decimal(1), timer_pace * Decimal("0.02"))
    return (
        f"{scope}_PACE_FROM_GARMIN_REPORTED_SPEED_DIFFERS_FROM_TIMER_PACE"
        if abs(pace_from_reported_speed - timer_pace) > tolerance
        else None
    )


_PARTIAL_QUALITY_WARNINGS = frozenset(
    {
        "ELAPSED_DURATION_UNAVAILABLE",
        "TIMER_DURATION_FALLBACK_INFERRED",
        "MOVING_DURATION_UNAVAILABLE",
        "POOL_LENGTH_FALLBACK_INFERRED",
        "LAP_MESSAGES_SYNTHESIZED",
        "LENGTH_MESSAGES_UNAVAILABLE",
        "UNKNOWN_LENGTH_TYPE",
        "UNASSIGNED_LENGTH_MESSAGES",
        "LAP_LENGTH_INDEX_BOUNDARY_INVALID",
        "LAP_LENGTH_INDEX_COUNT_MISMATCH",
        "LAP_LENGTH_INDEX_RANGE_OVERLAP",
        "LAP_IDLE_LENGTH_OWNERSHIP_INFERRED",
        "LAP_TIMER_DURATION_FALLBACK_INFERRED",
        "LAP_ELAPSED_DURATION_FALLBACK_INFERRED",
        "LENGTH_TIMER_DURATION_FALLBACK_INFERRED",
        "LENGTH_ELAPSED_DURATION_FALLBACK_INFERRED",
        "LAP_ACTIVE_LENGTH_DISTANCE_MISMATCH",
    }
)
_POOR_QUALITY_WARNING_SUFFIXES = (
    "_TIMER_EXCEEDS_ELAPSED",
    "_MOVING_EXCEEDS_TIMER",
    "_REST_EXCEEDS_TIMER",
    "_DURATION_DECOMPOSITION_INCONSISTENT",
)
_POOR_QUALITY_WARNINGS = frozenset(
    {
        "SESSION_ACTIVE_LENGTH_COUNT_MISMATCH",
        "SESSION_LENGTH_DISTANCE_MISMATCH",
        "ACTIVE_LENGTH_DISTANCE_INVARIANT_FAILED",
    }
)


def _data_quality(completeness: Decimal, warnings: Sequence[str]) -> DataQuality:
    base = (
        DataQuality.COMPLETE
        if completeness >= Decimal("0.8")
        else DataQuality.PARTIAL
        if completeness >= Decimal("0.5")
        else DataQuality.POOR
    )
    if base == DataQuality.POOR:
        return base
    if any(
        warning in _POOR_QUALITY_WARNINGS or warning.endswith(_POOR_QUALITY_WARNING_SUFFIXES)
        for warning in warnings
    ):
        return DataQuality.POOR
    if base == DataQuality.COMPLETE and any(
        warning in _PARTIAL_QUALITY_WARNINGS for warning in warnings
    ):
        return DataQuality.PARTIAL
    return base


def _length_type(message: Mapping[str, Any]) -> LengthType:
    raw_value = str(message.get("length_type", "")).strip().lower()
    if raw_value == LengthType.ACTIVE:
        return LengthType.ACTIVE
    if raw_value == LengthType.IDLE:
        return LengthType.IDLE
    return LengthType.UNKNOWN


def _stroke(message: Mapping[str, Any], fallback: str | None = None) -> str | None:
    value = message.get("swim_stroke")
    return str(value).strip().lower() if value is not None and str(value).strip() else fallback


def _lap_length_messages(
    raw_lap: Mapping[str, Any],
    raw_lengths: Sequence[Mapping[str, Any]],
    *,
    next_first_length_index: int | None,
    lap_position: int,
    lap_count: int,
    lap_offset: Decimal,
    lap_end: Decimal,
    origin: datetime | None,
    next_position: int,
) -> tuple[tuple[Mapping[str, Any], ...], int, tuple[str, ...]]:
    first = _integer(raw_lap.get("first_length_index"))
    count = _integer(raw_lap.get("num_lengths"))
    if first is not None and count is not None and first >= 0 and count >= 0:
        # first_length_index and num_lengths are the declared ownership facts.
        # The supplied Garmin pool FIT also proves one narrow exception: a
        # temporal lap can report count=0 while only IDLE messages occupy the
        # range before the next lap boundary. Preserve that inference visibly;
        # never absorb arbitrary ACTIVE/UNKNOWN extras into a lap.
        range_warnings: list[str] = []
        if first > len(raw_lengths):
            return (), next_position, ("LAP_LENGTH_INDEX_BOUNDARY_INVALID",)
        counted_end = first + count
        if lap_position == lap_count - 1:
            # With no following boundary, retain the declared count. Any
            # trailing messages remain visibly unassigned rather than being
            # silently attributed to the final lap.
            boundary_end = counted_end
        elif next_first_length_index is not None and first <= next_first_length_index <= len(
            raw_lengths
        ):
            if next_first_length_index < counted_end:
                # Prevent overlapping ownership; the following lap's explicit
                # first index is a harder boundary than the crossing count.
                boundary_end = next_first_length_index
                range_warnings.append("LAP_LENGTH_INDEX_RANGE_OVERLAP")
            elif next_first_length_index == counted_end:
                boundary_end = counted_end
            elif count == 0:
                candidate_extras = raw_lengths[first:next_first_length_index]
                if candidate_extras and all(
                    _length_type(item) == LengthType.IDLE for item in candidate_extras
                ):
                    boundary_end = next_first_length_index
                    range_warnings.append("LAP_IDLE_LENGTH_OWNERSHIP_INFERRED")
                else:
                    boundary_end = counted_end
                    range_warnings.append("LAP_LENGTH_INDEX_COUNT_MISMATCH")
            else:
                boundary_end = counted_end
                range_warnings.append("LAP_LENGTH_INDEX_COUNT_MISMATCH")
        else:
            boundary_end = counted_end
            range_warnings.append("LAP_LENGTH_INDEX_BOUNDARY_INVALID")
        start = min(len(raw_lengths), max(first, next_position))
        if start > first:
            range_warnings.append("LAP_LENGTH_INDEX_RANGE_OVERLAP")
        end = max(start, min(len(raw_lengths), boundary_end))
        return (
            tuple(raw_lengths[start:end]),
            max(next_position, end),
            tuple(dict.fromkeys(range_warnings)),
        )
    selected: list[Mapping[str, Any]] = []
    position = next_position
    while position < len(raw_lengths):
        raw_length = raw_lengths[position]
        length_start = _offset(raw_length.get("start_time"), origin, lap_offset)
        if lap_position < lap_count - 1 and length_start >= lap_end:
            break
        selected.append(raw_length)
        position += 1
    return tuple(selected), position, ()


class GarminFitActivityParser:
    NORMALIZER_VERSION = "2.1.0"

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
        fallback_pool_length_m: int | None,
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
        fallback_pool_length_m: int | None,
    ) -> NormalizedActivity:
        sessions = _messages(decoded, "session")
        raw_laps = _messages(decoded, "lap")
        has_source_laps = bool(raw_laps)
        raw_lengths = _messages(decoded, "length")
        records = _messages(decoded, "record")
        session = sessions[0] if sessions else {}
        warnings: list[str] = []
        perceived_effort_rpe, feeling_score = _session_evaluation(session, warnings)

        raw_pool_length = _whole_metres(session.get("pool_length"))
        raw_pool_length_unit = session.get("pool_length_unit")
        pool_length_unit = (
            str(raw_pool_length_unit).strip().lower()
            if raw_pool_length_unit is not None and str(raw_pool_length_unit).strip()
            else None
        )
        pool_from_garmin = raw_pool_length is not None and raw_pool_length > 0
        pool_length_m = (
            raw_pool_length
            if raw_pool_length is not None and raw_pool_length > 0
            else fallback_pool_length_m
        )
        if pool_length_m is None or pool_length_m <= 0:
            raise DomainError("FIT_PARSE_FAILED", "FIT pool length is missing or invalid.")
        if not pool_from_garmin:
            warnings.append("POOL_LENGTH_FALLBACK_INFERRED")

        typed_raw_lengths = tuple((item, _length_type(item)) for item in raw_lengths)
        active_raw_lengths = tuple(
            item for item, length_type in typed_raw_lengths if length_type == LengthType.ACTIVE
        )
        raw_active_length_count = _integer(session.get("num_active_lengths"))
        if raw_active_length_count is not None and raw_active_length_count != len(
            active_raw_lengths
        ):
            warnings.append("SESSION_ACTIVE_LENGTH_COUNT_MISMATCH")
        if any(length_type == LengthType.UNKNOWN for _, length_type in typed_raw_lengths):
            warnings.append("UNKNOWN_LENGTH_TYPE")
        calculated_distance = len(active_raw_lengths) * pool_length_m
        raw_explicit_distance = _whole_metres(session.get("total_distance"))
        distance_source = ProvenanceSource.INFERRED
        distance_transformation = "distance unavailable"
        if raw_explicit_distance is not None:
            # total_distance is a standard session FIT fact.  Active-length
            # distance is valuable corroborating evidence, but must never
            # silently replace a conflicting Garmin fact.
            distance_m = raw_explicit_distance
            distance_source = ProvenanceSource.GARMIN
            distance_transformation = "FIT SDK profile scaling to metres"
            if raw_lengths and calculated_distance != raw_explicit_distance:
                warnings.append("SESSION_LENGTH_DISTANCE_MISMATCH")
        elif raw_lengths:
            distance_m = calculated_distance
            distance_source = ProvenanceSource.DERIVED
            distance_transformation = "active length count * pool length metres"
        else:
            distance_m = 0
            warnings.append("DISTANCE_UNAVAILABLE")
        if not active_raw_lengths:
            warnings.append("LENGTH_MESSAGES_UNAVAILABLE")

        raw_elapsed_seconds = _optional_decimal(session.get("total_elapsed_time"))
        elapsed_from_garmin = raw_elapsed_seconds is not None
        elapsed_seconds = raw_elapsed_seconds if raw_elapsed_seconds is not None else ZERO
        if not elapsed_from_garmin:
            warnings.append("ELAPSED_DURATION_UNAVAILABLE")
        raw_timer_seconds = _optional_decimal(session.get("total_timer_time"))
        timer_from_garmin = raw_timer_seconds is not None
        timer_seconds = raw_timer_seconds if raw_timer_seconds is not None else elapsed_seconds
        if not timer_from_garmin:
            warnings.append("TIMER_DURATION_FALLBACK_INFERRED")
        moving_seconds = _optional_decimal(session.get("total_moving_time"))
        moving_from_garmin = moving_seconds is not None
        if moving_seconds is None:
            warnings.append("MOVING_DURATION_UNAVAILABLE")
        warnings.extend(
            _duration_warnings(
                elapsed=elapsed_seconds,
                timer=timer_seconds,
                moving=moving_seconds,
                scope="SESSION",
            )
        )
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
                    "total_moving_time": moving_seconds,
                    "total_distance": distance_m,
                    "swim_stroke": session.get("swim_stroke"),
                    "avg_speed": session.get("avg_speed"),
                    "enhanced_avg_speed": session.get("enhanced_avg_speed"),
                    "average_speed": session.get("average_speed"),
                    "total_strokes": session.get("total_strokes"),
                    "avg_cadence": session.get("avg_cadence"),
                    "avg_swolf": session.get("avg_swolf"),
                },
            )
            warnings.append("LAP_MESSAGES_SYNTHESIZED")

        length_position = 0
        cumulative_offset = ZERO
        for lap_position, raw_lap in enumerate(raw_laps):
            lap_warnings: list[str] = []
            raw_lap_elapsed = _optional_decimal(raw_lap.get("total_elapsed_time"))
            lap_elapsed_from_garmin = (raw_lap_elapsed is not None and has_source_laps) or (
                not has_source_laps and elapsed_from_garmin
            )
            lap_elapsed = (
                raw_lap_elapsed
                if raw_lap_elapsed is not None
                else elapsed_seconds
                if not has_source_laps
                else ZERO
            )
            raw_lap_timer = _optional_decimal(raw_lap.get("total_timer_time"))
            lap_timer_from_garmin = (raw_lap_timer is not None and has_source_laps) or (
                not has_source_laps and timer_from_garmin
            )
            lap_timer = raw_lap_timer if raw_lap_timer is not None else lap_elapsed
            if raw_lap_timer is None:
                lap_warnings.append("LAP_TIMER_DURATION_FALLBACK_INFERRED")
            if not lap_elapsed_from_garmin:
                lap_warnings.append("LAP_ELAPSED_DURATION_FALLBACK_INFERRED")
            lap_moving = _optional_decimal(raw_lap.get("total_moving_time"))
            lap_moving_from_garmin = (lap_moving is not None and has_source_laps) or (
                not has_source_laps and moving_from_garmin
            )
            if not lap_moving_from_garmin:
                lap_warnings.append("LAP_MOVING_DURATION_UNAVAILABLE")
            raw_lap_distance = _whole_metres(raw_lap.get("total_distance"))
            if not has_source_laps:
                lap_distance = distance_m
                lap_distance_source = distance_source
                lap_distance_raw_field = (
                    "session.total_distance" if distance_source == ProvenanceSource.GARMIN else None
                )
                lap_distance_transformation = distance_transformation
                lap_distance_interpretation = (
                    "documented" if distance_source == ProvenanceSource.GARMIN else "inferred"
                )
            elif raw_lap_distance is not None:
                lap_distance = raw_lap_distance
                lap_distance_source = ProvenanceSource.GARMIN
                lap_distance_raw_field = "lap.total_distance"
                lap_distance_transformation = "FIT SDK profile scaling to metres"
                lap_distance_interpretation = "documented"
            elif len(raw_laps) == 1 and distance_m > 0:
                lap_distance = distance_m
                lap_distance_source = ProvenanceSource.DERIVED
                lap_distance_raw_field = (
                    "session.total_distance" if raw_explicit_distance is not None else None
                )
                lap_distance_transformation = "single lap canonical session distance fallback"
                lap_distance_interpretation = "inferred"
            else:
                lap_distance = 0
                lap_distance_source = ProvenanceSource.INFERRED
                lap_distance_raw_field = None
                lap_distance_transformation = "value unavailable"
                lap_distance_interpretation = "inferred"
            lap_offset = _offset(raw_lap.get("start_time"), origin, cumulative_offset)
            lap_end = lap_offset + lap_elapsed
            next_first_length_index = (
                _integer(raw_laps[lap_position + 1].get("first_length_index"))
                if lap_position + 1 < len(raw_laps)
                else None
            )
            lap_raw_lengths, length_position, length_range_warnings = _lap_length_messages(
                raw_lap,
                raw_lengths,
                next_first_length_index=next_first_length_index,
                lap_position=lap_position,
                lap_count=len(raw_laps),
                lap_offset=lap_offset,
                lap_end=lap_end,
                origin=origin,
                next_position=length_position,
            )
            lap_warnings.extend(length_range_warnings)
            lap_active_lengths = tuple(
                item for item in lap_raw_lengths if _length_type(item) == LengthType.ACTIVE
            )
            lap_idle_lengths = tuple(
                item for item in lap_raw_lengths if _length_type(item) == LengthType.IDLE
            )
            lap_active_length_distance = len(lap_active_lengths) * pool_length_m
            if (
                has_source_laps
                and raw_lap_distance is not None
                and lap_raw_lengths
                and lap_active_length_distance != lap_distance
            ):
                lap_warnings.append("LAP_ACTIVE_LENGTH_DISTANCE_MISMATCH")
            lap_swim = (
                _milliseconds(
                    sum(
                        (
                            _decimal(
                                item.get("total_timer_time"),
                                _decimal(item.get("total_elapsed_time")),
                            )
                            for item in lap_active_lengths
                        ),
                        ZERO,
                    )
                )
                if lap_active_lengths
                else None
            )
            if lap_idle_lengths:
                lap_rest = _milliseconds(
                    sum(
                        (
                            _decimal(
                                item.get("total_timer_time"),
                                _decimal(item.get("total_elapsed_time")),
                            )
                            for item in lap_idle_lengths
                        ),
                        ZERO,
                    )
                )
            else:
                lap_rest = ZERO
                if lap_distance == 0 and lap_timer > 0:
                    lap_warnings.append("ZERO_DISTANCE_INTERVAL_WITHOUT_REST_EVIDENCE")
            lap_warnings.extend(
                _duration_warnings(
                    elapsed=lap_elapsed,
                    timer=lap_timer,
                    moving=lap_moving,
                    rest=lap_rest,
                    scope="LAP",
                )
            )
            lap_stationary = _stationary_duration(
                lap_timer, lap_moving, lap_rest, lap_warnings, scope="LAP"
            )
            raw_detected_stroke = _stroke(raw_lap)
            detected_stroke = raw_detected_stroke
            if raw_detected_stroke is not None:
                detected_stroke_source = ProvenanceSource.GARMIN
                detected_stroke_raw_field = f"{'lap' if has_source_laps else 'session'}.swim_stroke"
                detected_stroke_transformation = "normalize FIT swim_stroke enum to lowercase"
                detected_stroke_interpretation = "documented"
            else:
                detected_stroke_source = ProvenanceSource.INFERRED
                detected_stroke_raw_field = None
                detected_stroke_transformation = "value unavailable"
                detected_stroke_interpretation = "inferred"
            if detected_stroke is None:
                active_strokes = {
                    value for item in lap_active_lengths if (value := _stroke(item)) is not None
                }
                if len(active_strokes) == 1:
                    detected_stroke = next(iter(active_strokes))
                    detected_stroke_source = ProvenanceSource.DERIVED
                    detected_stroke_raw_field = "length.swim_stroke"
                    detected_stroke_transformation = "single active-length stroke"
                    detected_stroke_interpretation = "documented"
                elif len(active_strokes) > 1:
                    detected_stroke = "mixed"
                    detected_stroke_source = ProvenanceSource.DERIVED
                    detected_stroke_raw_field = "length.swim_stroke"
                    detected_stroke_transformation = "multiple active-length strokes"
                    detected_stroke_interpretation = "documented"
            stroke_count = _integer(raw_lap.get("total_strokes"))
            stroke_rate = (
                _decimal(raw_lap.get("avg_cadence"))
                if raw_lap.get("avg_cadence") is not None
                else None
            )
            lap_swolf_value = raw_lap.get("avg_swolf")
            lap_swolf = _decimal(lap_swolf_value) if lap_swolf_value is not None else None
            (
                reported_speed,
                pace_from_reported_speed,
                reported_speed_field,
            ) = _reported_speed_and_equivalent_pace(raw_lap)
            timer_pace = _pace(lap_timer, lap_distance)
            pace_warning = _pace_warning(pace_from_reported_speed, timer_pace, scope="LAP")
            if pace_warning is not None:
                lap_warnings.append(pace_warning)
            warnings.extend(lap_warnings)

            lap_raw_scope = "lap" if has_source_laps else "session"
            lap_provenance: JsonObject = {
                "distance_m": _fact(
                    lap_distance_source,
                    raw_field=lap_distance_raw_field,
                    transformation=lap_distance_transformation,
                    interpretation=lap_distance_interpretation,
                ),
                "detected_stroke": _fact(
                    detected_stroke_source,
                    raw_field=detected_stroke_raw_field,
                    transformation=detected_stroke_transformation,
                    interpretation=detected_stroke_interpretation,
                ),
                "stroke_count": _fact(
                    (
                        ProvenanceSource.GARMIN
                        if stroke_count is not None
                        else ProvenanceSource.INFERRED
                    ),
                    raw_field=(
                        f"{lap_raw_scope}.total_strokes" if stroke_count is not None else None
                    ),
                    transformation=(
                        "FIT swimming total_strokes field"
                        if stroke_count is not None
                        else "value unavailable"
                    ),
                    interpretation=("documented" if stroke_count is not None else "inferred"),
                ),
                "stroke_rate": _fact(
                    (
                        ProvenanceSource.GARMIN
                        if stroke_rate is not None
                        else ProvenanceSource.INFERRED
                    ),
                    raw_field=(f"{lap_raw_scope}.avg_cadence" if stroke_rate is not None else None),
                    transformation=(
                        "map generic FIT avg_cadence rpm to canonical stroke rate"
                        if stroke_rate is not None
                        else "value unavailable"
                    ),
                    # The profile documents avg_cadence as generic rpm, not
                    # explicitly as swimming strokes/min at lap/session scope.
                    interpretation="inferred",
                ),
                "swolf": _fact(
                    (
                        ProvenanceSource.GARMIN
                        if lap_swolf is not None
                        else ProvenanceSource.INFERRED
                    ),
                    raw_field=(f"{lap_raw_scope}.avg_swolf" if lap_swolf is not None else None),
                    transformation=(
                        "non-standard decoded lap/session field preserved"
                        if lap_swolf is not None
                        else "value unavailable"
                    ),
                    # avg_swolf is absent from the standard session/lap
                    # messages in the installed FIT Profile 21.208.
                    interpretation="inferred",
                ),
                "elapsed_seconds": _fact(
                    (
                        ProvenanceSource.GARMIN
                        if lap_elapsed_from_garmin
                        else ProvenanceSource.INFERRED
                    ),
                    raw_field=(
                        f"{lap_raw_scope}.total_elapsed_time" if lap_elapsed_from_garmin else None
                    ),
                    transformation=(
                        None if lap_elapsed_from_garmin else "session duration or zero fallback"
                    ),
                    interpretation=("documented" if lap_elapsed_from_garmin else "inferred"),
                ),
                "timer_seconds": _fact(
                    (
                        ProvenanceSource.GARMIN
                        if lap_timer_from_garmin
                        else ProvenanceSource.INFERRED
                    ),
                    raw_field=(
                        f"{lap_raw_scope}.total_timer_time" if lap_timer_from_garmin else None
                    ),
                    transformation=(
                        None
                        if lap_timer_from_garmin
                        else "lap elapsed duration or synthesized session timer fallback"
                    ),
                    interpretation=("documented" if lap_timer_from_garmin else "inferred"),
                ),
                "moving_seconds": _fact(
                    (
                        ProvenanceSource.GARMIN
                        if lap_moving_from_garmin
                        else ProvenanceSource.INFERRED
                    ),
                    raw_field=(
                        f"{lap_raw_scope}.total_moving_time" if lap_moving_from_garmin else None
                    ),
                    transformation=(None if lap_moving_from_garmin else "value unavailable"),
                    interpretation=("documented" if lap_moving_from_garmin else "inferred"),
                ),
                "swim_seconds": _fact(
                    ProvenanceSource.DERIVED,
                    transformation="sum(active length total_timer_time)",
                    interpretation="inferred",
                ),
                "rest_seconds": _fact(
                    (ProvenanceSource.DERIVED if lap_idle_lengths else ProvenanceSource.INFERRED),
                    raw_field=("length.length_type" if lap_idle_lengths else None),
                    transformation=(
                        "sum(idle length timer time)"
                        if lap_idle_lengths
                        else "no explicit rest evidence"
                    ),
                    interpretation="inferred",
                ),
                "stationary_seconds": _fact(
                    ProvenanceSource.DERIVED,
                    transformation="timer_seconds - moving_seconds - rest_seconds",
                ),
                "garmin_reported_speed_m_per_s": _fact(
                    (
                        ProvenanceSource.GARMIN
                        if reported_speed is not None
                        else ProvenanceSource.INFERRED
                    ),
                    raw_field=(
                        f"{lap_raw_scope}.{reported_speed_field}"
                        if reported_speed_field is not None
                        else None
                    ),
                    transformation=(
                        "FIT SDK profile scaling to metres per second"
                        if reported_speed is not None
                        else "value unavailable"
                    ),
                    interpretation=(
                        _speed_interpretation(reported_speed_field)
                        if reported_speed is not None
                        else "inferred"
                    ),
                    field_unit_semantics=(
                        _speed_field_unit_semantics(reported_speed_field)
                        if reported_speed is not None
                        else None
                    ),
                    calculation_basis=("inferred" if reported_speed is not None else None),
                ),
                "pace_from_garmin_reported_speed_seconds_per_100m": _fact(
                    ProvenanceSource.DERIVED,
                    raw_field=(
                        f"{lap_raw_scope}.{reported_speed_field}"
                        if reported_speed_field is not None
                        else None
                    ),
                    transformation="100 / garmin_reported_speed_m_per_s",
                    interpretation=(
                        _speed_interpretation(reported_speed_field)
                        if reported_speed is not None
                        else "inferred"
                    ),
                    input_calculation_basis=("inferred" if reported_speed is not None else None),
                ),
                "moving_pace_seconds_per_100m": _fact(
                    ProvenanceSource.DERIVED,
                    transformation="moving_seconds / distance_m * 100",
                ),
                "swim_pace_seconds_per_100m": _fact(
                    ProvenanceSource.DERIVED,
                    transformation="swim_seconds / distance_m * 100",
                ),
                "timer_pace_seconds_per_100m": _fact(
                    ProvenanceSource.DERIVED,
                    transformation="timer_seconds / distance_m * 100",
                ),
                "elapsed_pace_seconds_per_100m": _fact(
                    ProvenanceSource.DERIVED,
                    transformation="elapsed_seconds / distance_m * 100",
                ),
            }
            lap = ActivityLap(
                id=EntityId.new(),
                normalization_id=normalization_id,
                lap_index=lap_position,
                start_offset_seconds=lap_offset,
                elapsed_seconds=lap_elapsed,
                timer_seconds=lap_timer,
                moving_seconds=lap_moving,
                swim_seconds=lap_swim,
                rest_seconds=lap_rest,
                stationary_seconds=lap_stationary,
                distance_m=lap_distance,
                garmin_reported_speed_m_per_s=reported_speed,
                pace_from_garmin_reported_speed_seconds_per_100m=pace_from_reported_speed,
                moving_pace_seconds_per_100m=_pace(lap_moving, lap_distance),
                swim_pace_seconds_per_100m=_pace(lap_swim, lap_distance),
                timer_pace_seconds_per_100m=timer_pace,
                elapsed_pace_seconds_per_100m=_pace(lap_elapsed, lap_distance),
                avg_hr_bpm=_integer(raw_lap.get("avg_heart_rate")),
                max_hr_bpm=_integer(raw_lap.get("max_heart_rate")),
                stroke_type=detected_stroke,
                detected_stroke=detected_stroke,
                provenance=lap_provenance,
                quality_warnings=tuple(dict.fromkeys(lap_warnings)),
            )
            laps.append(lap)

            interval_type_raw_field: str | None
            if lap_distance == 0 and lap_timer > 0 and lap_idle_lengths:
                interval_type = IntervalType.REST
                interval_type_source = ProvenanceSource.DERIVED
                interval_type_raw_field = "length.length_type"
                interval_type_transformation = (
                    "zero-distance lap with standard FIT idle-length evidence"
                )
                interval_type_interpretation = "inferred"
            elif detected_stroke == "drill":
                interval_type = IntervalType.DRILL
                interval_type_source = ProvenanceSource.DERIVED
                interval_type_raw_field = detected_stroke_raw_field
                interval_type_transformation = "FIT swim_stroke=drill canonical classification"
                interval_type_interpretation = "documented"
            elif lap_distance > 0:
                interval_type = IntervalType.SWIM
                interval_type_source = ProvenanceSource.DERIVED
                interval_type_raw_field = lap_distance_raw_field
                interval_type_transformation = "positive-distance lap canonical classification"
                interval_type_interpretation = "inferred"
            else:
                interval_type = IntervalType.UNKNOWN
                interval_type_source = ProvenanceSource.INFERRED
                interval_type_raw_field = None
                interval_type_transformation = "insufficient FIT evidence for classification"
                interval_type_interpretation = "inferred"

            interval_id = EntityId.new()
            interval = ActivityInterval(
                id=interval_id,
                normalization_id=normalization_id,
                interval_index=lap_position,
                interval_type=interval_type.value,
                start_offset_seconds=lap_offset,
                duration_seconds=lap_timer,
                elapsed_seconds=lap_elapsed,
                timer_seconds=lap_timer,
                moving_seconds=lap_moving,
                swim_seconds=lap_swim,
                rest_seconds=lap_rest,
                stationary_seconds=lap_stationary,
                distance_m=lap_distance,
                pace_seconds_per_100m=timer_pace,
                garmin_reported_speed_m_per_s=reported_speed,
                pace_from_garmin_reported_speed_seconds_per_100m=pace_from_reported_speed,
                moving_pace_seconds_per_100m=_pace(lap_moving, lap_distance),
                swim_pace_seconds_per_100m=_pace(lap_swim, lap_distance),
                timer_pace_seconds_per_100m=timer_pace,
                elapsed_pace_seconds_per_100m=_pace(lap_elapsed, lap_distance),
                avg_hr_bpm=lap.avg_hr_bpm,
                max_hr_bpm=lap.max_hr_bpm,
                stroke_type=detected_stroke,
                detected_stroke=detected_stroke,
                stroke_count=stroke_count,
                stroke_rate=stroke_rate,
                swolf=lap_swolf,
                source={
                    "lap_message_index": _integer(raw_lap.get("message_index")) or lap_position,
                    "synthesized_from_session": not has_source_laps,
                },
                provenance={
                    **lap_provenance,
                    "interval_type": _fact(
                        interval_type_source,
                        raw_field=interval_type_raw_field,
                        transformation=interval_type_transformation,
                        interpretation=interval_type_interpretation,
                    ),
                },
                quality_warnings=tuple(dict.fromkeys(lap_warnings)),
            )
            intervals.append(interval)

            for raw_length in lap_raw_lengths:
                canonical_length_type = _length_type(raw_length)
                raw_length_type = raw_length.get("length_type")
                length_type_from_garmin = raw_length_type is not None and bool(
                    str(raw_length_type).strip()
                )
                recognized_length_type = canonical_length_type in {
                    LengthType.ACTIVE,
                    LengthType.IDLE,
                }
                length_elapsed = _optional_decimal(raw_length.get("total_elapsed_time"))
                length_elapsed_from_garmin = length_elapsed is not None
                raw_length_timer = _optional_decimal(raw_length.get("total_timer_time"))
                length_timer_from_garmin = raw_length_timer is not None
                length_timer = (
                    raw_length_timer if raw_length_timer is not None else length_elapsed or ZERO
                )
                if length_elapsed is None:
                    length_elapsed = length_timer
                length_moving = _optional_decimal(raw_length.get("total_moving_time"))
                length_moving_from_garmin = length_moving is not None
                length_distance = pool_length_m if canonical_length_type == LengthType.ACTIVE else 0
                if canonical_length_type == LengthType.ACTIVE:
                    length_distance_source = ProvenanceSource.DERIVED
                    length_distance_transformation = (
                        "active FIT length_type * normalized pool_length_m"
                    )
                    length_distance_interpretation = "inferred"
                elif canonical_length_type == LengthType.IDLE:
                    length_distance_source = ProvenanceSource.DERIVED
                    length_distance_transformation = "idle FIT length_type maps to zero distance"
                    length_distance_interpretation = "inferred"
                else:
                    length_distance_source = ProvenanceSource.INFERRED
                    length_distance_transformation = (
                        "unknown length_type cannot establish swum distance"
                    )
                    length_distance_interpretation = "inferred"
                length_swim = (
                    length_timer
                    if canonical_length_type == LengthType.ACTIVE
                    else ZERO
                    if canonical_length_type == LengthType.IDLE
                    else None
                )
                length_rest = (
                    length_timer
                    if canonical_length_type == LengthType.IDLE
                    else ZERO
                    if canonical_length_type == LengthType.ACTIVE
                    else None
                )
                length_warnings = _duration_warnings(
                    elapsed=length_elapsed,
                    timer=length_timer,
                    moving=length_moving,
                    rest=length_rest,
                    scope="LENGTH",
                )
                if not length_timer_from_garmin:
                    length_warnings.append("LENGTH_TIMER_DURATION_FALLBACK_INFERRED")
                if not length_elapsed_from_garmin:
                    length_warnings.append("LENGTH_ELAPSED_DURATION_FALLBACK_INFERRED")
                length_stationary = _stationary_duration(
                    length_timer,
                    length_moving,
                    length_rest,
                    length_warnings,
                    scope="LENGTH",
                )
                raw_length_stroke = _stroke(raw_length)
                length_stroke_raw_field: str | None
                if canonical_length_type == LengthType.ACTIVE and raw_length_stroke is not None:
                    length_stroke = raw_length_stroke
                    length_stroke_source = ProvenanceSource.GARMIN
                    length_stroke_raw_field = "length.swim_stroke"
                    length_stroke_transformation = "normalize FIT swim_stroke enum to lowercase"
                    length_stroke_interpretation = "documented"
                elif canonical_length_type == LengthType.ACTIVE and detected_stroke is not None:
                    length_stroke = detected_stroke
                    length_stroke_source = ProvenanceSource.DERIVED
                    length_stroke_raw_field = detected_stroke_raw_field
                    length_stroke_transformation = "canonical lap detected_stroke fallback"
                    length_stroke_interpretation = "inferred"
                else:
                    length_stroke = None
                    length_stroke_source = ProvenanceSource.INFERRED
                    length_stroke_raw_field = None
                    length_stroke_transformation = (
                        "not applicable to non-active length"
                        if canonical_length_type != LengthType.ACTIVE
                        else "value unavailable"
                    )
                    length_stroke_interpretation = "inferred"
                (
                    length_reported_speed,
                    length_pace_from_reported_speed,
                    length_speed_field,
                ) = _reported_speed_and_equivalent_pace(raw_length)
                length_timer_pace = _pace(length_timer, length_distance)
                length_pace_warning = _pace_warning(
                    length_pace_from_reported_speed, length_timer_pace, scope="LENGTH"
                )
                if length_pace_warning is not None:
                    length_warnings.append(length_pace_warning)
                warnings.extend(length_warnings)
                strokes = _integer(raw_length.get("total_strokes"))
                length_stroke_rate = (
                    _decimal(raw_length.get("avg_swimming_cadence"))
                    if raw_length.get("avg_swimming_cadence") is not None
                    else None
                )
                swolf_value = raw_length.get("avg_swolf")
                swolf = (
                    _decimal(swolf_value)
                    if swolf_value is not None
                    else (
                        length_timer + Decimal(strokes)
                        if canonical_length_type == LengthType.ACTIVE and strokes is not None
                        else None
                    )
                )
                lengths.append(
                    ActivityLength(
                        id=EntityId.new(),
                        normalization_id=normalization_id,
                        interval_id=interval_id,
                        length_index=len(lengths),
                        length_type=canonical_length_type.value,
                        distance_m=length_distance,
                        duration_seconds=length_timer,
                        elapsed_seconds=length_elapsed,
                        timer_seconds=length_timer,
                        moving_seconds=length_moving,
                        swim_seconds=length_swim,
                        rest_seconds=length_rest,
                        stationary_seconds=length_stationary,
                        garmin_reported_speed_m_per_s=length_reported_speed,
                        pace_from_garmin_reported_speed_seconds_per_100m=length_pace_from_reported_speed,
                        moving_pace_seconds_per_100m=_pace(length_moving, length_distance),
                        swim_pace_seconds_per_100m=_pace(length_swim, length_distance),
                        timer_pace_seconds_per_100m=length_timer_pace,
                        elapsed_pace_seconds_per_100m=_pace(length_elapsed, length_distance),
                        stroke_type=length_stroke,
                        detected_stroke=length_stroke,
                        stroke_count=strokes,
                        stroke_rate=length_stroke_rate,
                        swolf=swolf,
                        avg_hr_bpm=_integer(raw_length.get("avg_heart_rate")),
                        provenance={
                            "length_type": _fact(
                                (
                                    ProvenanceSource.GARMIN
                                    if length_type_from_garmin
                                    else ProvenanceSource.INFERRED
                                ),
                                raw_field=(
                                    "length.length_type" if length_type_from_garmin else None
                                ),
                                transformation=(
                                    "normalize standard FIT length_type enum"
                                    if recognized_length_type
                                    else "unrecognized FIT length_type value mapped to unknown"
                                    if length_type_from_garmin
                                    else "missing field maps to unknown"
                                ),
                                interpretation=(
                                    "documented" if recognized_length_type else "inferred"
                                ),
                            ),
                            "distance_m": _fact(
                                length_distance_source,
                                raw_field=(
                                    "length.length_type" if length_type_from_garmin else None
                                ),
                                transformation=length_distance_transformation,
                                interpretation=length_distance_interpretation,
                            ),
                            "detected_stroke": _fact(
                                length_stroke_source,
                                raw_field=length_stroke_raw_field,
                                transformation=length_stroke_transformation,
                                interpretation=length_stroke_interpretation,
                            ),
                            "stroke_count": _fact(
                                (
                                    ProvenanceSource.GARMIN
                                    if strokes is not None
                                    else ProvenanceSource.INFERRED
                                ),
                                raw_field=("length.total_strokes" if strokes is not None else None),
                                transformation=(
                                    "standard FIT strokes count"
                                    if strokes is not None
                                    else "value unavailable"
                                ),
                                interpretation=(
                                    "documented" if strokes is not None else "inferred"
                                ),
                            ),
                            "stroke_rate": _fact(
                                (
                                    ProvenanceSource.GARMIN
                                    if length_stroke_rate is not None
                                    else ProvenanceSource.INFERRED
                                ),
                                raw_field=(
                                    "length.avg_swimming_cadence"
                                    if length_stroke_rate is not None
                                    else None
                                ),
                                transformation=(
                                    "FIT SDK profile scaling to strokes per minute"
                                    if length_stroke_rate is not None
                                    else "value unavailable"
                                ),
                                interpretation=(
                                    "documented" if length_stroke_rate is not None else "inferred"
                                ),
                            ),
                            "elapsed_seconds": _fact(
                                (
                                    ProvenanceSource.GARMIN
                                    if length_elapsed_from_garmin
                                    else ProvenanceSource.INFERRED
                                ),
                                raw_field=(
                                    "length.total_elapsed_time"
                                    if length_elapsed_from_garmin
                                    else "length.total_timer_time"
                                    if raw_length_timer is not None
                                    else None
                                ),
                                transformation=(
                                    None
                                    if length_elapsed_from_garmin
                                    else "timer duration fallback"
                                    if raw_length_timer is not None
                                    else "zero fallback"
                                ),
                                interpretation=(
                                    "documented" if length_elapsed_from_garmin else "inferred"
                                ),
                            ),
                            "timer_seconds": _fact(
                                (
                                    ProvenanceSource.GARMIN
                                    if length_timer_from_garmin
                                    else ProvenanceSource.INFERRED
                                ),
                                raw_field=(
                                    "length.total_timer_time"
                                    if length_timer_from_garmin
                                    else "length.total_elapsed_time"
                                    if raw_length.get("total_elapsed_time") is not None
                                    else None
                                ),
                                transformation=(
                                    None
                                    if length_timer_from_garmin
                                    else "elapsed duration fallback"
                                    if raw_length.get("total_elapsed_time") is not None
                                    else "zero fallback"
                                ),
                                interpretation=(
                                    "documented" if length_timer_from_garmin else "inferred"
                                ),
                            ),
                            "swim_seconds": _fact(
                                ProvenanceSource.DERIVED,
                                raw_field=(
                                    "length.total_timer_time"
                                    if length_timer_from_garmin
                                    else "length.total_elapsed_time"
                                    if length_elapsed_from_garmin
                                    else None
                                ),
                                transformation="active length canonical timer duration",
                                interpretation="inferred",
                            ),
                            "rest_seconds": _fact(
                                ProvenanceSource.DERIVED,
                                raw_field=(
                                    "length.total_timer_time"
                                    if length_timer_from_garmin
                                    else "length.total_elapsed_time"
                                    if length_elapsed_from_garmin
                                    else None
                                ),
                                transformation="idle length canonical timer duration",
                                interpretation="inferred",
                            ),
                            "moving_seconds": _fact(
                                (
                                    ProvenanceSource.GARMIN
                                    if length_moving_from_garmin
                                    else ProvenanceSource.INFERRED
                                ),
                                raw_field=(
                                    "length.total_moving_time"
                                    if length_moving_from_garmin
                                    else None
                                ),
                                transformation=(
                                    "non-standard decoded length field preserved"
                                    if length_moving_from_garmin
                                    else "value unavailable"
                                ),
                                # FIT Profile 21.208 defines total_moving_time for
                                # session/lap, but not for a standard length message.
                                interpretation="inferred",
                            ),
                            "stationary_seconds": _fact(
                                ProvenanceSource.DERIVED,
                                transformation="timer_seconds - moving_seconds - rest_seconds",
                            ),
                            "garmin_reported_speed_m_per_s": _fact(
                                (
                                    ProvenanceSource.GARMIN
                                    if length_reported_speed is not None
                                    else ProvenanceSource.INFERRED
                                ),
                                raw_field=(
                                    f"length.{length_speed_field}"
                                    if length_speed_field is not None
                                    else None
                                ),
                                transformation=(
                                    "FIT SDK profile scaling to metres per second"
                                    if length_reported_speed is not None
                                    else "value unavailable"
                                ),
                                interpretation=(
                                    _speed_interpretation(length_speed_field)
                                    if length_reported_speed is not None
                                    else "inferred"
                                ),
                                field_unit_semantics=(
                                    _speed_field_unit_semantics(length_speed_field)
                                    if length_reported_speed is not None
                                    else None
                                ),
                                calculation_basis=(
                                    "inferred" if length_reported_speed is not None else None
                                ),
                            ),
                            "pace_from_garmin_reported_speed_seconds_per_100m": _fact(
                                ProvenanceSource.DERIVED,
                                raw_field=(
                                    f"length.{length_speed_field}" if length_speed_field else None
                                ),
                                transformation="100 / garmin_reported_speed_m_per_s",
                                interpretation=(
                                    _speed_interpretation(length_speed_field)
                                    if length_reported_speed is not None
                                    else "inferred"
                                ),
                                input_calculation_basis=(
                                    "inferred" if length_reported_speed is not None else None
                                ),
                            ),
                            "moving_pace_seconds_per_100m": _fact(
                                ProvenanceSource.DERIVED,
                                transformation="moving_seconds / distance_m * 100",
                            ),
                            "swim_pace_seconds_per_100m": _fact(
                                ProvenanceSource.DERIVED,
                                transformation="swim_seconds / distance_m * 100",
                            ),
                            "timer_pace_seconds_per_100m": _fact(
                                ProvenanceSource.DERIVED,
                                transformation="timer_seconds / distance_m * 100",
                            ),
                            "elapsed_pace_seconds_per_100m": _fact(
                                ProvenanceSource.DERIVED,
                                transformation="elapsed_seconds / distance_m * 100",
                            ),
                            "swolf": _fact(
                                (
                                    ProvenanceSource.GARMIN
                                    if swolf_value is not None
                                    else ProvenanceSource.DERIVED
                                ),
                                raw_field=("length.avg_swolf" if swolf_value is not None else None),
                                transformation=(
                                    "non-standard decoded length field preserved"
                                    if swolf_value is not None
                                    else "timer_seconds + stroke_count"
                                ),
                                interpretation="inferred",
                            ),
                        },
                        quality_warnings=tuple(dict.fromkeys(length_warnings)),
                    )
                )
            cumulative_offset = max(cumulative_offset, lap_end)

        swim_seconds = (
            _milliseconds(
                sum(
                    (
                        item.swim_seconds
                        for item in lengths
                        if item.length_type == LengthType.ACTIVE and item.swim_seconds is not None
                    ),
                    ZERO,
                )
            )
            if any(item.length_type == LengthType.ACTIVE for item in lengths)
            else None
        )
        rest_seconds = _milliseconds(sum((item.rest_seconds for item in intervals), ZERO))
        stationary_seconds = _stationary_duration(
            timer_seconds,
            moving_seconds,
            rest_seconds,
            warnings,
            scope="SESSION",
        )
        (
            garmin_reported_speed,
            pace_from_garmin_reported_speed,
            session_speed_field,
        ) = _reported_speed_and_equivalent_pace(session)
        timer_pace = _pace(timer_seconds, distance_m)
        session_pace_warning = _pace_warning(
            pace_from_garmin_reported_speed,
            timer_pace,
            scope="SESSION",
        )
        if session_pace_warning is not None:
            warnings.append(session_pace_warning)
        if len(lengths) != len(raw_lengths):
            warnings.append("UNASSIGNED_LENGTH_MESSAGES")
        parsed_active_length_count = sum(item.length_type == LengthType.ACTIVE for item in lengths)
        parsed_active_distance = sum(
            item.distance_m for item in lengths if item.length_type == LengthType.ACTIVE
        )
        if active_raw_lengths and parsed_active_distance != distance_m:
            warnings.append("ACTIVE_LENGTH_DISTANCE_INVARIANT_FAILED")

        completeness_parts = (
            bool(sessions),
            distance_m > 0,
            elapsed_seconds > 0,
            timer_seconds > 0,
            moving_seconds is not None,
            has_source_laps,
            any(item.length_type == LengthType.ACTIVE for item in lengths),
            any(item.get("heart_rate") is not None for item in records)
            or session.get("avg_heart_rate") is not None,
            any(item.stroke_count is not None for item in lengths),
            any(item.swolf is not None for item in lengths),
        )
        completeness = Decimal(sum(completeness_parts)) / Decimal(len(completeness_parts))
        quality = _data_quality(completeness, warnings)
        pool_provenance = _fact(
            ProvenanceSource.GARMIN if pool_from_garmin else ProvenanceSource.INFERRED,
            raw_field="session.pool_length" if pool_from_garmin else None,
            transformation=(
                "FIT SDK profile scaling to metres"
                if pool_from_garmin
                else (
                    "corroborated ingestion fallback from activity summary and/or "
                    "distance per active length"
                )
            ),
            interpretation=("documented" if pool_from_garmin else "inferred"),
        )
        if raw_pool_length is not None:
            pool_provenance["garmin_value_m"] = raw_pool_length
        if not pool_from_garmin:
            pool_provenance["fallback_value_m"] = pool_length_m
        distance_provenance = _fact(
            distance_source,
            raw_field=(
                "session.total_distance" if distance_source == ProvenanceSource.GARMIN else None
            ),
            transformation=distance_transformation,
            interpretation=(
                "documented" if distance_source == ProvenanceSource.GARMIN else "inferred"
            ),
        )
        if raw_explicit_distance is not None:
            distance_provenance["garmin_value_m"] = raw_explicit_distance
        if raw_lengths:
            distance_provenance["active_length_value_m"] = calculated_distance
        active_length_count_provenance = _fact(
            ProvenanceSource.DERIVED if raw_lengths else ProvenanceSource.INFERRED,
            raw_field="length.length_type" if raw_lengths else None,
            transformation=(
                "count persisted decoded active length messages"
                if raw_lengths
                else "length messages unavailable"
            ),
            interpretation=("documented" if raw_lengths else "inferred"),
        )
        if raw_active_length_count is not None:
            active_length_count_provenance["garmin_reported_value"] = raw_active_length_count
            active_length_count_provenance["garmin_raw_field"] = "session.num_active_lengths"
        active_length_count_provenance["decoded_message_value"] = len(active_raw_lengths)
        active_length_count_provenance["persisted_value"] = parsed_active_length_count
        pool_length_unit_provenance = _fact(
            (
                ProvenanceSource.GARMIN
                if pool_length_unit is not None
                else ProvenanceSource.INFERRED
            ),
            raw_field=("session.pool_length_unit" if pool_length_unit is not None else None),
            transformation=(None if pool_length_unit is not None else "value unavailable"),
            interpretation=("documented" if pool_length_unit is not None else "inferred"),
        )
        if pool_length_unit is not None:
            pool_length_unit_provenance["garmin_value"] = pool_length_unit
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
            swim_seconds=swim_seconds,
            rest_seconds=rest_seconds,
            stationary_seconds=stationary_seconds,
            garmin_reported_speed_m_per_s=garmin_reported_speed,
            pace_from_garmin_reported_speed_seconds_per_100m=pace_from_garmin_reported_speed,
            moving_pace_seconds_per_100m=_pace(moving_seconds, distance_m),
            swim_pace_seconds_per_100m=_pace(swim_seconds, distance_m),
            timer_pace_seconds_per_100m=timer_pace,
            session_pace_seconds_per_100m=_pace(elapsed_seconds, distance_m),
            perceived_effort_rpe=perceived_effort_rpe,
            feeling_score=feeling_score,
            active_length_count=parsed_active_length_count,
            completeness=completeness.quantize(Decimal("0.001")),
            quality=quality,
            warnings=tuple(dict.fromkeys(warnings)),
            provenance={
                "pool_length_m": pool_provenance,
                "pool_length_unit": pool_length_unit_provenance,
                "distance_m": distance_provenance,
                "active_length_count": active_length_count_provenance,
                "elapsed_seconds": _fact(
                    (ProvenanceSource.GARMIN if elapsed_from_garmin else ProvenanceSource.INFERRED),
                    raw_field=("session.total_elapsed_time" if elapsed_from_garmin else None),
                    transformation=(None if elapsed_from_garmin else "zero fallback"),
                    interpretation=("documented" if elapsed_from_garmin else "inferred"),
                ),
                "timer_seconds": _fact(
                    (ProvenanceSource.GARMIN if timer_from_garmin else ProvenanceSource.INFERRED),
                    raw_field=("session.total_timer_time" if timer_from_garmin else None),
                    transformation=(None if timer_from_garmin else "elapsed duration fallback"),
                    interpretation=("documented" if timer_from_garmin else "inferred"),
                ),
                "moving_seconds": _fact(
                    (ProvenanceSource.GARMIN if moving_from_garmin else ProvenanceSource.INFERRED),
                    raw_field=("session.total_moving_time" if moving_from_garmin else None),
                    transformation=(None if moving_from_garmin else "value unavailable"),
                    interpretation=("documented" if moving_from_garmin else "inferred"),
                ),
                "swim_seconds": _fact(
                    ProvenanceSource.DERIVED,
                    transformation="sum(active length total_timer_time)",
                    interpretation="inferred",
                ),
                "rest_seconds": _fact(
                    ProvenanceSource.DERIVED,
                    transformation="sum(interval rest backed by idle length evidence)",
                    interpretation="inferred",
                ),
                "stationary_seconds": _fact(
                    ProvenanceSource.DERIVED,
                    transformation="timer_seconds - moving_seconds - rest_seconds",
                ),
                "garmin_reported_speed_m_per_s": _fact(
                    (
                        ProvenanceSource.GARMIN
                        if garmin_reported_speed is not None
                        else ProvenanceSource.INFERRED
                    ),
                    raw_field=(
                        f"session.{session_speed_field}"
                        if session_speed_field is not None
                        else None
                    ),
                    transformation=(
                        "FIT SDK profile scaling to metres per second"
                        if garmin_reported_speed is not None
                        else "value unavailable"
                    ),
                    interpretation=(
                        _speed_interpretation(session_speed_field)
                        if garmin_reported_speed is not None
                        else "inferred"
                    ),
                    field_unit_semantics=(
                        _speed_field_unit_semantics(session_speed_field)
                        if garmin_reported_speed is not None
                        else None
                    ),
                    calculation_basis=("inferred" if garmin_reported_speed is not None else None),
                ),
                "pace_from_garmin_reported_speed_seconds_per_100m": _fact(
                    ProvenanceSource.DERIVED,
                    raw_field=(f"session.{session_speed_field}" if session_speed_field else None),
                    transformation="100 / garmin_reported_speed_m_per_s",
                    interpretation=(
                        _speed_interpretation(session_speed_field)
                        if garmin_reported_speed is not None
                        else "inferred"
                    ),
                    input_calculation_basis=(
                        "inferred" if garmin_reported_speed is not None else None
                    ),
                ),
                "moving_pace_seconds_per_100m": _fact(
                    ProvenanceSource.DERIVED,
                    transformation="moving_seconds / distance_m * 100",
                ),
                "swim_pace_seconds_per_100m": _fact(
                    ProvenanceSource.DERIVED,
                    transformation="swim_seconds / distance_m * 100",
                ),
                "timer_pace_seconds_per_100m": _fact(
                    ProvenanceSource.DERIVED,
                    transformation="timer_seconds / distance_m * 100",
                ),
                "session_pace_seconds_per_100m": _fact(
                    ProvenanceSource.DERIVED,
                    transformation="elapsed_seconds / distance_m * 100",
                ),
                "perceived_effort_rpe": _fact(
                    (
                        ProvenanceSource.GARMIN
                        if perceived_effort_rpe is not None
                        else ProvenanceSource.INFERRED
                    ),
                    raw_field=("session.workout_rpe" if perceived_effort_rpe is not None else None),
                    transformation=(
                        "divide FIT Borg CR10 score by 10"
                        if perceived_effort_rpe is not None
                        else "value unavailable or invalid"
                    ),
                    interpretation="documented",
                ),
                "feeling_score": _fact(
                    (
                        ProvenanceSource.GARMIN
                        if feeling_score is not None
                        else ProvenanceSource.INFERRED
                    ),
                    raw_field=("session.workout_feel" if feeling_score is not None else None),
                    transformation=(
                        "preserve FIT 0-100 workout feeling score"
                        if feeling_score is not None
                        else "value unavailable or invalid"
                    ),
                    interpretation="documented",
                ),
            },
        )
        return NormalizedActivity(normalization, tuple(laps), tuple(intervals), tuple(lengths))
