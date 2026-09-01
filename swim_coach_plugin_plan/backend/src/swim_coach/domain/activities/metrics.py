"""Provider-neutral swimming analytics built only from canonical normalized facts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import fields, is_dataclass
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import cast

from swim_coach.domain.activities.contextual import (
    ExpandedPlannedStep,
    QualityLevel,
    StepAlignment,
    WorkoutAdherence,
    align_planned_steps,
    analyze_continuity,
    assess_data_quality,
    build_speed_endurance_profile,
    detect_interval_outliers,
    expand_planned_steps,
    freestyle_work_intervals,
    group_equivalent_sets,
    pace_for,
    planned_stroke_context_used,
)
from swim_coach.domain.activities.entities import (
    ActivityAnalysis,
    ActivityInterval,
    DataQuality,
    NormalizedActivity,
    SessionFeedback,
)
from swim_coach.domain.shared.types import JsonObject, JsonValue
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
    """Calculate sRPE using the caller-selected duration basis."""

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


def _json_value(value: object) -> JsonValue:
    """Convert immutable analysis records to JSON without losing Decimal precision."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, StrEnum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {item.name: _json_value(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_value(item) for item in value]
    raise TypeError(f"analysis value is not JSON serializable: {type(value).__name__}")


def _planned_overlay(
    intervals: tuple[ActivityInterval, ...],
    adherence: WorkoutAdherence | None,
    planned_steps: tuple[ExpandedPlannedStep, ...],
) -> tuple[dict[str, object], ...]:
    alignment_by_index: dict[int, StepAlignment] = {}
    if adherence is not None:
        alignment_by_index = {
            item.actual_index: item
            for item in adherence.alignments
            if item.actual_index is not None
        }
    records: list[dict[str, object]] = []
    for item in intervals:
        alignment = alignment_by_index.get(item.interval_index)
        planned_step = (
            planned_steps[alignment.planned_index]
            if alignment is not None and alignment.planned_index < len(planned_steps)
            else None
        )
        matched_planned_rest = (
            alignment is not None
            and alignment.planned_interval_type == "REST"
            and item.distance_m == 0
        )
        normalized_rest_evidence = item.interval_type.lower() == "rest" or item.rest_seconds > 0
        rest_contextualized_from_plan = matched_planned_rest and not normalized_rest_evidence
        interval_type = "rest" if matched_planned_rest else item.interval_type
        rest_seconds = (
            item.rest_seconds
            if item.rest_seconds > 0 or not matched_planned_rest
            else item.timer_seconds or item.duration_seconds
        )
        records.append(
            {
                "id": item.id,
                "interval_index": item.interval_index,
                "interval_type": interval_type,
                "interval_type_source": (
                    "planned_workout" if rest_contextualized_from_plan else "normalized_activity"
                ),
                "distance_m": item.distance_m,
                "elapsed_seconds": item.elapsed_seconds,
                "timer_seconds": item.timer_seconds,
                "moving_seconds": item.moving_seconds,
                "swim_seconds": item.swim_seconds,
                "rest_seconds": rest_seconds,
                "stationary_seconds": item.stationary_seconds,
                "pace_from_garmin_reported_speed_seconds_per_100m": (
                    item.pace_from_garmin_reported_speed_seconds_per_100m
                ),
                "moving_pace_seconds_per_100m": item.moving_pace_seconds_per_100m,
                "swim_pace_seconds_per_100m": item.swim_pace_seconds_per_100m,
                "timer_pace_seconds_per_100m": item.timer_pace_seconds_per_100m,
                "detected_stroke": item.detected_stroke,
                "planned_stroke": (
                    alignment.planned_stroke if alignment is not None else item.planned_stroke
                ),
                "planned_role": (
                    alignment.planned_role if alignment is not None else item.planned_role
                ),
                "planned_intensity": planned_step.intensity if planned_step is not None else None,
                "set_id": alignment.set_id if alignment is not None else None,
                "repetition_index": (alignment.repetition_index if alignment is not None else None),
                "planned_rest_duration_s": (
                    alignment.planned_duration_s
                    if alignment is not None and alignment.planned_interval_type == "REST"
                    else None
                ),
                "target_min_pace_s_per_100m": (
                    planned_step.target_min_pace_s_per_100m if planned_step is not None else None
                ),
                "target_max_pace_s_per_100m": (
                    planned_step.target_max_pace_s_per_100m if planned_step is not None else None
                ),
                "stroke_count": item.stroke_count,
                "stroke_rate": item.stroke_rate,
                "swolf": item.swolf,
                "quality_warnings": item.quality_warnings,
            }
        )
    return tuple(records)


def _length_overlay(
    normalized: NormalizedActivity,
    interval_records: tuple[dict[str, object], ...],
) -> tuple[dict[str, object], ...]:
    interval_by_id = {
        item.id: (position, interval_records[position])
        for position, item in enumerate(normalized.intervals)
    }
    localized_stationary_by_interval: dict[EntityId, Decimal] = {}
    for length in normalized.lengths:
        if length.stationary_seconds is not None and length.stationary_seconds > 0:
            localized_stationary_by_interval[length.interval_id] = (
                localized_stationary_by_interval.get(length.interval_id, Decimal(0))
                + length.stationary_seconds
            )
    records: list[dict[str, object]] = []
    previous_interval_position: int | None = None
    for item in normalized.lengths:
        interval_position, interval = interval_by_id[item.interval_id]
        interval_stationary = interval.get("stationary_seconds")
        stationary_location_unknown = (
            isinstance(interval_stationary, Decimal)
            and interval_stationary > 0
            and localized_stationary_by_interval.get(item.interval_id, Decimal(0))
            != interval_stationary
        )
        break_before = False
        if (
            previous_interval_position is not None
            and interval_position > previous_interval_position
        ):
            crossed = interval_records[previous_interval_position + 1 : interval_position + 1]
            break_before = any(
                str(candidate["interval_type"]).lower() == "rest"
                or str(candidate.get("planned_role") or "").upper() == "REST"
                for candidate in crossed
            )
        records.append(
            {
                "length_index": item.length_index,
                "length_type": item.length_type,
                "distance_m": item.distance_m,
                "elapsed_seconds": item.elapsed_seconds,
                "timer_seconds": item.timer_seconds,
                "moving_seconds": item.moving_seconds,
                "swim_seconds": item.swim_seconds,
                "rest_seconds": item.rest_seconds,
                "stationary_seconds": item.stationary_seconds,
                "moving_pace_seconds_per_100m": item.moving_pace_seconds_per_100m,
                "swim_pace_seconds_per_100m": item.swim_pace_seconds_per_100m,
                "timer_pace_seconds_per_100m": item.timer_pace_seconds_per_100m,
                "detected_stroke": item.detected_stroke,
                "planned_stroke": interval.get("planned_stroke"),
                "planned_role": interval.get("planned_role"),
                "stroke_count": item.stroke_count,
                "stroke_rate": item.stroke_rate,
                "swolf": item.swolf,
                "continuity_break_before": break_before,
                "continuity_boundary_uncertain": stationary_location_unknown,
            }
        )
        previous_interval_position = interval_position
    return tuple(records)


def _selected_profile_pace_basis(records: Sequence[object]) -> tuple[str, tuple[str, ...]]:
    """Choose one explicit basis for cross-set profiles and disclose the choice.

    Equivalent-set analysis selects its basis independently per set.  The broader
    speed/endurance profile needs one comparable basis, so it uses the basis with
    the greatest coverage among freestyle WORK intervals (moving wins ties).
    """

    comparable = freestyle_work_intervals(records, include_outliers=True)
    counts = {
        basis: sum(pace_for(item, basis=basis) is not None for item in comparable)
        for basis in ("moving", "swim", "timer")
    }
    basis = max(counts, key=lambda candidate: (counts[candidate], -tuple(counts).index(candidate)))
    if counts[basis] == 0:
        return "moving", ("PROFILE_PACE_SERIES_UNAVAILABLE",)
    reasons = () if basis == "moving" else (f"PROFILE_ANALYSIS_USES_{basis.upper()}_PACE",)
    return basis, reasons


def _duration_for_basis(item: Mapping[str, object], basis: str) -> Decimal | None:
    raw = item.get(f"{basis}_seconds")
    return raw if isinstance(raw, Decimal) and raw >= 0 else None


def _distance_value(item: Mapping[str, object]) -> int:
    raw = item["distance_m"]
    if isinstance(raw, int) and not isinstance(raw, bool):
        return raw
    raise TypeError("canonical distance_m must be an integer")


def _aggregate_paces(records: Sequence[Mapping[str, object]]) -> JsonObject:
    result: JsonObject = {}
    for basis in ("moving", "swim", "timer"):
        selected = tuple(
            (item, duration)
            for item in records
            if _distance_value(item) > 0
            and (duration := _duration_for_basis(item, basis)) is not None
        )
        distance = sum(_distance_value(item) for item, _ in selected)
        duration = sum((value for _, value in selected), Decimal(0))
        result[basis] = {
            "pace_s_per_100m": _decimal_json(pace_seconds_per_100m(duration, distance)),
            "distance_m": distance,
            "interval_count": len(selected),
        }
    return result


def _contextual_paces(records: tuple[dict[str, object], ...]) -> JsonObject:
    result: JsonObject = {}
    for role in ("WARMUP", "WORK", "DRILL", "COOLDOWN"):
        selected = tuple(
            item
            for item in records
            if str(item.get("planned_role") or "").upper() == role
            and str(item["interval_type"]).lower() != "rest"
        )
        result[role.lower()] = _aggregate_paces(selected)
    freestyle = cast(
        tuple[Mapping[str, object], ...],
        freestyle_work_intervals(records, include_outliers=False),
    )
    freestyle_summary = _aggregate_paces(freestyle)
    freestyle_summary["quality"] = {
        "level": (
            QualityLevel.MEDIUM.value
            if any(planned_stroke_context_used(item) for item in freestyle)
            else QualityLevel.HIGH.value
        ),
        "reasons": (
            ["PLANNED_STROKE_CONTEXT_USED"]
            if any(planned_stroke_context_used(item) for item in freestyle)
            else []
        ),
    }
    result["freestyle_work"] = freestyle_summary
    return result


def _stroke_efficiency(
    length_records: tuple[dict[str, object], ...], pool_length_m: int
) -> list[JsonValue]:
    pace_band_width = Decimal(15)
    grouped: dict[tuple[str, int, str, int | None], list[dict[str, object]]] = {}
    for item in length_records:
        if item["length_type"] != "active" or _distance_value(item) <= 0:
            continue
        stroke = str(item.get("detected_stroke") or "unknown").lower()
        planned_role = str(item.get("planned_role") or "UNKNOWN").upper()
        swim_pace = pace_for(item, basis="swim")
        pace_band = (
            int((swim_pace / pace_band_width).to_integral_value(rounding=ROUND_FLOOR)) * 15
            if swim_pace is not None
            else None
        )
        grouped.setdefault((stroke, _distance_value(item), planned_role, pace_band), []).append(
            item
        )
    result: list[JsonValue] = []
    ordered = sorted(
        grouped.items(),
        key=lambda entry: (
            entry[0][0],
            entry[0][1],
            entry[0][2],
            -1 if entry[0][3] is None else entry[0][3],
        ),
    )
    for (stroke, distance_m, planned_role, pace_band), items in ordered:
        strokes = tuple(
            int(value) for item in items if isinstance((value := item.get("stroke_count")), int)
        )
        swolf = tuple(value for item in items if isinstance((value := item.get("swolf")), Decimal))
        quality_reasons: list[str] = []
        if pace_band is None:
            quality_reasons.append("MISSING_SWIM_PACE_CONTEXT")
        if len(strokes) < len(items):
            quality_reasons.append("MISSING_STROKE_COUNT")
        if len(swolf) < len(items):
            quality_reasons.append("MISSING_SWOLF")
        if not strokes and not swolf:
            quality_level = QualityLevel.LOW
        elif quality_reasons or len(items) < 3:
            if len(items) < 3:
                quality_reasons.append("LIMITED_SAMPLE")
            quality_level = QualityLevel.MEDIUM
        else:
            quality_level = QualityLevel.HIGH
        result.append(
            {
                "pool_length_m": pool_length_m,
                "length_distance_m": distance_m,
                "stroke": stroke,
                "planned_role": planned_role,
                "pace_context": {
                    "basis": "swim",
                    "lower_s_per_100m": pace_band,
                    "upper_exclusive_s_per_100m": (
                        pace_band + int(pace_band_width) if pace_band is not None else None
                    ),
                },
                "sample_count": len(items),
                "stroke_count_sample_count": len(strokes),
                "swolf_sample_count": len(swolf),
                "average_strokes_per_length": _decimal_json(
                    _rounded(Decimal(sum(strokes)) / Decimal(len(strokes)), _HUNDREDTH)
                    if strokes
                    else None
                ),
                "average_swolf": _decimal_json(
                    _rounded(sum(swolf, Decimal(0)) / Decimal(len(swolf)), _HUNDREDTH)
                    if swolf
                    else None
                ),
                "paces": _aggregate_paces(items),
                "quality": {
                    "level": quality_level.value,
                    "reasons": list(dict.fromkeys(quality_reasons)),
                },
                "interpretation": (
                    "compare_only_same_pool_length_stroke_distance_role_and_pace_band"
                ),
            }
        )
    return result


def _longest_below_goal_pace(
    lengths: tuple[dict[str, object], ...], goal_pace_s_per_100m: Decimal
) -> JsonObject | None:
    blocks: list[list[dict[str, object]]] = []
    current: list[dict[str, object]] = []
    for item in lengths:
        is_freestyle = str(item.get("detected_stroke") or "").lower() in {
            "freestyle",
            "front_crawl",
            "crawl",
        }
        excluded_role = str(item.get("planned_role") or "").upper() in {
            "DRILL",
            "COOLDOWN",
        }
        stationary = item.get("stationary_seconds")
        isolating_boundary = (isinstance(stationary, Decimal) and stationary > 0) or bool(
            item.get("continuity_boundary_uncertain")
        )
        if (item.get("continuity_break_before") or isolating_boundary) and current:
            blocks.append(current)
            current = []
        if item["length_type"] == "active" and is_freestyle and not excluded_role:
            current.append(item)
            if isolating_boundary:
                blocks.append(current)
                current = []
        elif current:
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)
    best: tuple[int, Decimal, int, int] | None = None
    for block in blocks:
        for start in range(len(block)):
            distance = 0
            duration = Decimal(0)
            for end in range(start, len(block)):
                swim_duration = block[end].get("swim_seconds")
                if not isinstance(swim_duration, Decimal):
                    break
                distance += _distance_value(block[end])
                duration += swim_duration
                pace = pace_seconds_per_100m(duration, distance)
                if pace is not None and pace <= goal_pace_s_per_100m:
                    candidate = (distance, duration, start, end)
                    if (
                        best is None
                        or candidate[0] > best[0]
                        or (candidate[0] == best[0] and candidate[1] < best[1])
                    ):
                        best = candidate
    if best is None:
        return None
    distance, duration, start, end = best
    return {
        "distance_m": distance,
        "swim_duration_s": _decimal_json(_rounded(duration)),
        "swim_pace_s_per_100m": _decimal_json(pace_seconds_per_100m(duration, distance)),
        "start_length_offset": start,
        "end_length_offset": end,
        "target_pace_s_per_100m": _decimal_json(goal_pace_s_per_100m),
    }


def _analysis_quality(level: QualityLevel) -> DataQuality:
    return {
        QualityLevel.HIGH: DataQuality.COMPLETE,
        QualityLevel.MEDIUM: DataQuality.PARTIAL,
        QualityLevel.LOW: DataQuality.POOR,
    }[level]


def analyze_swim(
    normalized: NormalizedActivity,
    *,
    user_id: UserId,
    analysis_version: str,
    planned_workout_id: EntityId | None = None,
    planned_distance_m: int | None = None,
    planned_workout: object | None = None,
    goal_distance_m: int = 2_000,
    goal_pace_s_per_100m: Decimal = Decimal("135"),
    feedback: SessionFeedback | None = None,
) -> ActivityAnalysis:
    """Create an immutable contextual analysis from explicit normalized inputs."""

    normalization = normalized.normalization
    planned_steps = expand_planned_steps(planned_workout) if planned_workout is not None else ()
    adherence = (
        align_planned_steps(planned_steps, normalized.intervals, pace_basis="best_available")
        if planned_steps
        else None
    )
    interval_records = _planned_overlay(normalized.intervals, adherence, planned_steps)
    length_records = _length_overlay(normalized, interval_records)
    profile_basis, profile_flags = _selected_profile_pace_basis(interval_records)
    sets = group_equivalent_sets(interval_records, pace_basis="best_available")
    set_basis = "per_set_explicit"
    set_basis_flags = tuple(
        f"SET_ANALYSIS_USES_{item.pace_basis.upper()}_PACE"
        for item in sets
        if item.pace_basis != "moving"
    )
    basis_flags = tuple(dict.fromkeys((*profile_flags, *set_basis_flags)))
    outliers = detect_interval_outliers(interval_records, pace_basis=profile_basis)
    continuity = analyze_continuity(length_records)
    profile = build_speed_endurance_profile(
        interval_records,
        lengths=length_records,
        activity=normalization,
        pace_basis=profile_basis,
        goal_distance_m=goal_distance_m,
        goal_pace_s_per_100m=goal_pace_s_per_100m,
    )
    pool_fact = normalization.provenance.get("pool_length_m")
    pool_inferred = isinstance(pool_fact, Mapping) and pool_fact.get("source") == "inferred"
    context_flags = tuple(
        dict.fromkeys(
            "REST_CLASSIFIED_FROM_PLANNED_WORKOUT"
            for item in interval_records
            if item.get("interval_type_source") == "planned_workout"
        )
    )
    quality = assess_data_quality(
        normalization,
        intervals=interval_records,
        lengths=length_records,
        alignments=adherence.alignments if adherence is not None else (),
        pool_length_inferred=pool_inferred,
        warnings=(
            *normalization.warnings,
            *context_flags,
            *(("PACE_OUTLIERS_DETECTED",) if outliers else ()),
        ),
    )
    explicit_rest = sum(
        (
            item["rest_seconds"]
            for item in interval_records
            if isinstance(item["rest_seconds"], Decimal)
        ),
        Decimal(0),
    )
    contextual_stationary = normalization.stationary_seconds
    if normalization.moving_seconds is not None:
        candidate_stationary = (
            normalization.timer_seconds - normalization.moving_seconds - explicit_rest
        )
        if candidate_stationary >= 0:
            contextual_stationary = _rounded(candidate_stationary)
    planned_actual: JsonValue
    if adherence is not None:
        planned_actual = _json_value(adherence)
    elif planned_distance_m is not None:
        planned_actual = {
            "planned_distance_m": planned_distance_m,
            "actual_distance_m": normalization.distance_m,
            "distance_difference_m": normalization.distance_m - planned_distance_m,
            "distance_adherence_ratio": _decimal_json(
                completion_ratio(normalization.distance_m, planned_distance_m)
            ),
            "quality": {"level": "LOW", "reasons": ["STEP_ALIGNMENT_UNAVAILABLE"]},
        }
    else:
        planned_actual = None
    load = srpe_load(normalization.timer_seconds, feedback.rpe) if feedback else None
    best_set = min(sets, key=lambda item: item.mean_pace_s_per_100m, default=None)
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
        _rounded(
            sum(length_strokes, Decimal(0)) / Decimal(len(length_strokes)),
            _HUNDREDTH,
        )
        if length_strokes
        else None
    )
    metrics: JsonObject = {
        "distance_m": normalization.distance_m,
        "durations": {
            "elapsed_s": _decimal_json(normalization.elapsed_seconds),
            "timer_s": _decimal_json(normalization.timer_seconds),
            "moving_s": _decimal_json(normalization.moving_seconds),
            "swim_s": _decimal_json(normalization.swim_seconds),
            "rest_s": _decimal_json(explicit_rest),
            "stationary_s": _decimal_json(contextual_stationary),
        },
        "paces": {
            "pace_from_garmin_reported_speed_s_per_100m": _decimal_json(
                normalization.pace_from_garmin_reported_speed_seconds_per_100m
            ),
            "moving_s_per_100m": _decimal_json(normalization.moving_pace_seconds_per_100m),
            "swim_s_per_100m": _decimal_json(normalization.swim_pace_seconds_per_100m),
            "timer_s_per_100m": _decimal_json(normalization.timer_pace_seconds_per_100m),
            "session_s_per_100m": _decimal_json(normalization.session_pace_seconds_per_100m),
        },
        "contextual_paces": _contextual_paces(interval_records),
        "set_pace_basis": set_basis,
        "profile_pace_basis": profile_basis,
        "sets": _json_value(sets),
        "outliers": _json_value(outliers),
        "continuity": _json_value(continuity),
        "longest_distance_below_goal_pace": _longest_below_goal_pace(
            length_records, goal_pace_s_per_100m
        ),
        "speed_endurance": _json_value(profile),
        "goal_readiness": _json_value(profile.goal_readiness),
        "planned_vs_actual": planned_actual,
        "stroke_efficiency": _stroke_efficiency(length_records, normalization.pool_length_m),
        "srpe": {
            "load": _decimal_json(load),
            "rpe": feedback.rpe if feedback else None,
            "duration_basis": "timer_duration_s",
            "duration_s": _decimal_json(normalization.timer_seconds),
        },
        "data_quality": _json_value(quality),
        "active_length_count": normalization.active_length_count,
        "pool_length_m": normalization.pool_length_m,
        "completeness": _decimal_json(normalization.completeness),
        # Frozen v1 aliases. Their historic basis was timer time; v2 consumers use paces.
        "average_pace_seconds_per_100m": _decimal_json(normalization.timer_pace_seconds_per_100m),
        "best_interval_pace_seconds_per_100m": _decimal_json(
            best_set.best_pace_s_per_100m if best_set is not None else None
        ),
        "total_rest_seconds": _decimal_json(explicit_rest),
        "consistency_cv": _decimal_json(
            best_set.coefficient_of_variation if best_set is not None else None
        ),
        "fade_percent": _decimal_json(best_set.fade_percent if best_set is not None else None),
        "completion_ratio": _decimal_json(
            completion_ratio(normalization.distance_m, planned_distance_m)
            if planned_distance_m is not None
            else None
        ),
        "average_swolf": _decimal_json(average_swolf),
        "average_strokes_per_length": _decimal_json(average_strokes),
        "srpe_load": _decimal_json(load),
    }
    flags = tuple(
        dict.fromkeys(
            (
                *normalization.warnings,
                *context_flags,
                *basis_flags,
                *quality.reasons,
                *continuity.quality_reasons,
            )
        )
    )
    summary: JsonObject = {
        "headline": "Análise contextual da atividade",
        "pace_semantics": "explicit_basis_only",
        "set_pace_basis": set_basis,
        "profile_pace_basis": profile_basis,
        "quality": quality.level.value,
        "medical_interpretation": False,
        "css_estimated": False,
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
        flags=flags,
        quality=_analysis_quality(quality.level),
        summary=summary,
        planned_workout_id=planned_workout_id,
    )
