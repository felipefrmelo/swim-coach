"""Deterministic initial swimming analytics with explicit rounding and zero handling."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from swim_coach.domain.activities.entities import (
    ActivityAnalysis,
    NormalizedActivity,
    SessionFeedback,
)
from swim_coach.domain.shared.types import JsonObject
from swim_coach.domain.shared.value_objects import EntityId, UserId

_MILLISECOND = Decimal("0.001")
_HUNDREDTH = Decimal("0.01")


def _rounded(value: Decimal, quantum: Decimal = _MILLISECOND) -> Decimal:
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


def pace_seconds_per_100m(duration_seconds: Decimal, distance_m: int) -> Decimal | None:
    """Return pace rounded to milliseconds; zero distance yields no metric."""

    if duration_seconds < 0 or distance_m < 0:
        raise ValueError("duration and distance cannot be negative")
    if distance_m == 0:
        return None
    return _rounded(duration_seconds / Decimal(distance_m) * Decimal(100))


def completion_ratio(completed_distance_m: int, planned_distance_m: int) -> Decimal | None:
    if completed_distance_m < 0 or planned_distance_m < 0:
        raise ValueError("distances cannot be negative")
    if planned_distance_m == 0:
        return None
    return _rounded(Decimal(completed_distance_m) / Decimal(planned_distance_m))


def srpe_load(duration_seconds: Decimal, rpe: int) -> Decimal:
    if duration_seconds < 0 or not 1 <= rpe <= 10:
        raise ValueError("sRPE requires non-negative duration and RPE from 1 to 10")
    return _rounded(duration_seconds / Decimal(60) * Decimal(rpe), _HUNDREDTH)


def coefficient_of_variation(values: tuple[Decimal, ...]) -> Decimal | None:
    """Population CV for at least two positive comparable pace values."""

    comparable = tuple(value for value in values if value > 0)
    if len(comparable) < 2:
        return None
    mean = sum(comparable, Decimal(0)) / Decimal(len(comparable))
    if mean == 0:
        return None
    variance = sum((value - mean) ** 2 for value in comparable) / Decimal(len(comparable))
    return _rounded(variance.sqrt() / mean, Decimal("0.0001"))


def fade_percent(values: tuple[Decimal, ...]) -> Decimal | None:
    """Compare first and last thirds; at least six comparable samples are required."""

    comparable = tuple(value for value in values if value > 0)
    if len(comparable) < 6:
        return None
    group_size = len(comparable) // 3
    first = sum(comparable[:group_size], Decimal(0)) / Decimal(group_size)
    last = sum(comparable[-group_size:], Decimal(0)) / Decimal(group_size)
    if first == 0:
        return None
    return _rounded((last - first) / first * Decimal(100), _HUNDREDTH)


def _decimal_json(value: Decimal | None) -> str | None:
    return format(value, "f") if value is not None else None


def analyze_swim(
    normalized: NormalizedActivity,
    *,
    user_id: UserId,
    analysis_version: str,
    planned_workout_id: EntityId | None = None,
    planned_distance_m: int | None = None,
    feedback: SessionFeedback | None = None,
) -> ActivityAnalysis:
    """Create an immutable analysis from exact normalized inputs."""

    work_intervals = tuple(
        item
        for item in normalized.intervals
        if item.interval_type == "work" and item.distance_m > 0
    )
    interval_paces = tuple(
        item.pace_seconds_per_100m
        for item in work_intervals
        if item.pace_seconds_per_100m is not None
    )
    normalization = normalized.normalization
    average_pace = pace_seconds_per_100m(
        normalization.moving_seconds,
        normalization.distance_m,
    )
    total_rest = sum((item.rest_seconds for item in work_intervals), Decimal(0))
    cv = coefficient_of_variation(interval_paces)
    fade = fade_percent(interval_paces)
    ratio = (
        completion_ratio(normalization.distance_m, planned_distance_m)
        if planned_distance_m is not None
        else None
    )
    load = srpe_load(normalization.moving_seconds, feedback.rpe) if feedback else None
    length_swolf = tuple(item.swolf for item in normalized.lengths if item.swolf is not None)
    average_swolf = (
        _rounded(sum(length_swolf, Decimal(0)) / Decimal(len(length_swolf)), _HUNDREDTH)
        if length_swolf
        else None
    )
    length_strokes = tuple(
        Decimal(item.stroke_count) for item in normalized.lengths if item.stroke_count is not None
    )
    average_strokes = (
        _rounded(sum(length_strokes, Decimal(0)) / Decimal(len(length_strokes)), _HUNDREDTH)
        if length_strokes
        else None
    )
    flags = list(normalization.warnings)
    if not interval_paces:
        flags.append("PACE_SERIES_UNAVAILABLE")
    if cv is None:
        flags.append("CONSISTENCY_SAMPLE_INSUFFICIENT")
    if fade is None:
        flags.append("FADE_SAMPLE_INSUFFICIENT")
    if not length_swolf:
        flags.append("SWOLF_UNAVAILABLE")
    metrics: JsonObject = {
        "distance_m": normalization.distance_m,
        "elapsed_seconds": _decimal_json(normalization.elapsed_seconds),
        "timer_seconds": _decimal_json(normalization.timer_seconds),
        "moving_seconds": _decimal_json(normalization.moving_seconds),
        "average_pace_seconds_per_100m": _decimal_json(average_pace),
        "best_interval_pace_seconds_per_100m": _decimal_json(min(interval_paces, default=None)),
        "total_rest_seconds": _decimal_json(total_rest),
        "consistency_cv": _decimal_json(cv),
        "fade_percent": _decimal_json(fade),
        "completion_ratio": _decimal_json(ratio),
        "average_swolf": _decimal_json(average_swolf),
        "average_strokes_per_length": _decimal_json(average_strokes),
        "srpe_load": _decimal_json(load),
        "active_length_count": normalization.active_length_count,
        "pool_length_m": normalization.pool_length_m,
        "completeness": _decimal_json(normalization.completeness),
    }
    summary: JsonObject = {
        "headline": "Análise reproduzível da atividade",
        "pace_context": "lower_is_better",
        "quality": normalization.quality.value,
        "medical_interpretation": False,
    }
    return ActivityAnalysis(
        id=EntityId.new(),
        user_id=user_id,
        activity_id=normalization.activity_id,
        normalization_id=normalization.id,
        analysis_version=analysis_version,
        parser_version=normalization.parser_version,
        input_checksum=normalization.input_checksum,
        pool_length_m=normalization.pool_length_m,
        metrics=metrics,
        flags=tuple(dict.fromkeys(flags)),
        quality=normalization.quality,
        summary=summary,
        planned_workout_id=planned_workout_id,
    )
