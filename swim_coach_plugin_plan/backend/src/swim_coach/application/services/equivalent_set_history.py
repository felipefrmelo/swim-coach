"""Historical comparisons for genuinely equivalent canonical swim sets."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, NotRequired, TypedDict

_MILLISECOND = Decimal("0.001")


class _Observation(TypedDict):
    started_at_utc: datetime
    distance_m: int
    stroke: str
    planned_role: str
    planned_intensity: str | None
    target_min_pace_s_per_100m: Decimal | None
    target_max_pace_s_per_100m: Decimal | None
    repetition_count: int
    pace_basis: str
    mean_pace_s_per_100m: Decimal
    coefficient_of_variation: Decimal | None
    fade_percent: Decimal | None
    actual_rest_duration_s: Decimal | None
    planned_rest_duration_s: Decimal | None
    average_strokes_per_length: Decimal | None
    average_swolf: Decimal | None
    rpe: Decimal | None
    session_quality: str
    set_quality: str
    equivalent_blocks_in_session: NotRequired[int]


def _mapping(value: object) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _decimal(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() else None


def _integer(value: object) -> int | None:
    number = _decimal(value)
    if number is None or number != number.to_integral_value():
        return None
    return int(number)


def _number(value: Decimal | None) -> int | float | None:
    if value is None:
        return None
    rounded = value.quantize(_MILLISECOND, rounding=ROUND_HALF_UP)
    return int(rounded) if rounded == rounded.to_integral_value() else float(rounded)


def _mean(values: Sequence[Decimal]) -> Decimal | None:
    if not values:
        return None
    return sum(values, start=Decimal(0)) / Decimal(len(values))


def _delta(latest: Decimal | None, first: Decimal | None) -> int | float | None:
    return _number(latest - first) if latest is not None and first is not None else None


def _matching_efficiency(
    metrics: Mapping[str, Any],
    *,
    stroke: str,
    planned_role: str,
    pace_basis: str,
    mean_pace: Decimal,
) -> tuple[Decimal | None, Decimal | None]:
    """Return efficiency only when its swim-pace context matches unambiguously."""

    if pace_basis != "swim":
        return None, None
    raw_groups = metrics.get("stroke_efficiency")
    if not isinstance(raw_groups, Sequence) or isinstance(raw_groups, (str, bytes)):
        return None, None
    candidates: list[Mapping[str, Any]] = []
    for raw_group in raw_groups:
        group = _mapping(raw_group)
        if group is None:
            continue
        if str(group.get("stroke") or "").upper() != stroke:
            continue
        if str(group.get("planned_role") or "").upper() != planned_role:
            continue
        pace_context = _mapping(group.get("pace_context"))
        lower = _decimal(pace_context.get("lower_s_per_100m")) if pace_context else None
        upper = _decimal(pace_context.get("upper_exclusive_s_per_100m")) if pace_context else None
        if lower is not None and upper is not None and lower <= mean_pace < upper:
            candidates.append(group)
    if len(candidates) != 1:
        return None, None
    return (
        _decimal(candidates[0].get("average_strokes_per_length")),
        _decimal(candidates[0].get("average_swolf")),
    )


def _observation(
    *,
    started_at_utc: datetime,
    set_record: Mapping[str, Any],
    metrics: Mapping[str, Any],
    session_quality: str,
) -> _Observation | None:
    key = _mapping(set_record.get("key"))
    paces = set_record.get("paces_s_per_100m")
    if key is None or not isinstance(paces, Sequence) or isinstance(paces, (str, bytes)):
        return None
    indexed_repetitions: set[int] = set()
    has_index_metadata = False
    for field in (
        "interval_indices",
        "excluded_outlier_indices",
        "excluded_stroke_mismatch_indices",
        "missing_pace_indices",
    ):
        raw_indices = set_record.get(field)
        if not isinstance(raw_indices, Sequence) or isinstance(raw_indices, (str, bytes)):
            continue
        has_index_metadata = True
        for raw_index in raw_indices:
            index = _integer(raw_index)
            if index is not None and index >= 0:
                indexed_repetitions.add(index)
    # paces contains only usable measurements. Historical equivalence must use
    # the complete executed set geometry, including missing/outlier repetitions,
    # or a 5x80 with one missing pace would be mixed with a complete 4x80.
    repetition_count = len(indexed_repetitions) if has_index_metadata else len(paces)
    distance_m = _integer(key.get("distance_m"))
    pace_basis = str(set_record.get("pace_basis") or "").lower()
    if distance_m is None or distance_m <= 0 or repetition_count < 2 or not pace_basis:
        return None
    mean_pace = _decimal(set_record.get("mean_pace_s_per_100m"))
    if mean_pace is None or mean_pace <= 0:
        return None
    stroke = str(key.get("stroke") or "UNKNOWN").upper()
    planned_role = str(key.get("planned_role") or "OTHER").upper()
    raw_intensity = key.get("planned_intensity")
    planned_intensity = str(raw_intensity).upper() if raw_intensity is not None else None
    average_strokes, average_swolf = _matching_efficiency(
        metrics,
        stroke=stroke,
        planned_role=planned_role,
        pace_basis=pace_basis,
        mean_pace=mean_pace,
    )
    srpe = _mapping(metrics.get("srpe"))
    return {
        "started_at_utc": started_at_utc,
        "distance_m": distance_m,
        "stroke": stroke,
        "planned_role": planned_role,
        "planned_intensity": planned_intensity,
        "target_min_pace_s_per_100m": _decimal(key.get("target_min_pace_s_per_100m")),
        "target_max_pace_s_per_100m": _decimal(key.get("target_max_pace_s_per_100m")),
        "repetition_count": repetition_count,
        "pace_basis": pace_basis,
        "mean_pace_s_per_100m": mean_pace,
        "coefficient_of_variation": _decimal(set_record.get("coefficient_of_variation")),
        "fade_percent": _decimal(set_record.get("fade_percent")),
        "actual_rest_duration_s": _decimal(set_record.get("actual_rest_duration_s")),
        "planned_rest_duration_s": _decimal(set_record.get("planned_rest_duration_s")),
        "average_strokes_per_length": average_strokes,
        "average_swolf": average_swolf,
        "rpe": _decimal(srpe.get("rpe")) if srpe is not None else None,
        "session_quality": session_quality,
        "set_quality": str(set_record.get("quality") or "LOW").upper(),
    }


def _collapse_session(observations: Sequence[_Observation]) -> _Observation:
    """Collapse duplicate equivalent blocks in one session without inventing an order."""

    first = observations[0]

    def averaged(field: str) -> Decimal | None:
        values = tuple(
            value for item in observations if isinstance((value := item.get(field)), Decimal)
        )
        return _mean(values)

    mean_pace = averaged("mean_pace_s_per_100m") or first["mean_pace_s_per_100m"]
    return _Observation(
        started_at_utc=first["started_at_utc"],
        distance_m=first["distance_m"],
        stroke=first["stroke"],
        planned_role=first["planned_role"],
        planned_intensity=first["planned_intensity"],
        target_min_pace_s_per_100m=first["target_min_pace_s_per_100m"],
        target_max_pace_s_per_100m=first["target_max_pace_s_per_100m"],
        repetition_count=first["repetition_count"],
        pace_basis=first["pace_basis"],
        mean_pace_s_per_100m=mean_pace,
        coefficient_of_variation=averaged("coefficient_of_variation"),
        fade_percent=averaged("fade_percent"),
        actual_rest_duration_s=averaged("actual_rest_duration_s"),
        planned_rest_duration_s=averaged("planned_rest_duration_s"),
        average_strokes_per_length=averaged("average_strokes_per_length"),
        average_swolf=averaged("average_swolf"),
        rpe=averaged("rpe"),
        session_quality=min(
            (item["session_quality"] for item in observations),
            key=lambda value: {"LOW": 0, "MEDIUM": 1, "HIGH": 2}.get(value, 0),
        ),
        set_quality=min(
            (item["set_quality"] for item in observations),
            key=lambda value: {"LOW": 0, "MEDIUM": 1, "HIGH": 2}.get(value, 0),
        ),
        equivalent_blocks_in_session=len(observations),
    )


def historical_equivalent_set_trends(
    samples: Sequence[tuple[datetime, Mapping[str, Any]]],
) -> list[dict[str, object]]:
    """Compare sets only when distance, stroke, role, repetitions and context match.

    ``samples`` must contain an activity UTC timestamp and its internal v2 analysis
    metrics.  A trend requires at least two distinct sessions.  Pace bases and planned
    intensity, target pace range and rest totals are part of the signature, so moving
    pace is never compared with timer pace and materially different prescriptions do
    not share a trend.
    """

    grouped: dict[
        tuple[
            int,
            int | None,
            str,
            str,
            str | None,
            Decimal | None,
            Decimal | None,
            int,
            str,
            Decimal | None,
        ],
        dict[datetime, list[_Observation]],
    ] = {}
    for started_at_utc, metrics in samples:
        raw_sets = metrics.get("sets")
        if not isinstance(raw_sets, Sequence) or isinstance(raw_sets, (str, bytes)):
            continue
        pool_length_m = _integer(metrics.get("pool_length_m"))
        quality = _mapping(metrics.get("data_quality"))
        session_quality = str(quality.get("level") if quality is not None else "LOW").upper()
        for raw_set in raw_sets:
            set_record = _mapping(raw_set)
            if set_record is None:
                continue
            observation = _observation(
                started_at_utc=started_at_utc,
                set_record=set_record,
                metrics=metrics,
                session_quality=session_quality,
            )
            if observation is None:
                continue
            planned_rest = observation["planned_rest_duration_s"]
            signature = (
                observation["distance_m"],
                pool_length_m,
                str(observation["stroke"]),
                str(observation["planned_role"]),
                observation["planned_intensity"],
                observation["target_min_pace_s_per_100m"],
                observation["target_max_pace_s_per_100m"],
                observation["repetition_count"],
                str(observation["pace_basis"]),
                planned_rest if isinstance(planned_rest, Decimal) else None,
            )
            grouped.setdefault(signature, {}).setdefault(started_at_utc, []).append(observation)

    trends: list[dict[str, object]] = []
    for signature, by_session in grouped.items():
        if len(by_session) < 2:
            continue
        observations = [_collapse_session(by_session[start]) for start in sorted(by_session)]
        first = observations[0]
        latest = observations[-1]
        first_pace = first["mean_pace_s_per_100m"]
        latest_pace = latest["mean_pace_s_per_100m"]
        first_cv = first.get("coefficient_of_variation")
        latest_cv = latest.get("coefficient_of_variation")
        first_fade = first.get("fade_percent")
        latest_fade = latest.get("fade_percent")
        first_rest = first.get("actual_rest_duration_s")
        latest_rest = latest.get("actual_rest_duration_s")
        first_strokes = first.get("average_strokes_per_length")
        latest_strokes = latest.get("average_strokes_per_length")
        first_swolf = first.get("average_swolf")
        latest_swolf = latest.get("average_swolf")
        first_rpe = first.get("rpe")
        latest_rpe = latest.get("rpe")
        complete_context = all(
            isinstance(value, Decimal)
            for value in (first_cv, latest_cv, first_fade, latest_fade, first_rest, latest_rest)
        )
        low_quality_session = any(item["session_quality"] == "LOW" for item in observations)
        medium_quality_session = any(item["session_quality"] == "MEDIUM" for item in observations)
        low_quality_set = any(item["set_quality"] == "LOW" for item in observations)
        medium_quality_set = any(item["set_quality"] == "MEDIUM" for item in observations)
        low_quality = low_quality_session or low_quality_set
        medium_quality = medium_quality_session or medium_quality_set
        confidence = (
            "HIGH"
            if len(observations) >= 4
            and complete_context
            and not low_quality
            and not medium_quality
            else "MEDIUM"
            if complete_context and not low_quality
            else "LOW"
        )
        reasons = []
        if len(observations) < 4:
            reasons.append("FEWER_THAN_FOUR_EQUIVALENT_SESSIONS")
        if not complete_context:
            reasons.append("MISSING_CV_FADE_OR_REST_CONTEXT")
        if low_quality_session:
            reasons.append("LOW_QUALITY_SESSION_INCLUDED")
        if medium_quality_session:
            reasons.append("MEDIUM_QUALITY_SESSION_INCLUDED")
        if low_quality_set:
            reasons.append("LOW_QUALITY_SET_INCLUDED")
        if medium_quality_set:
            reasons.append("MEDIUM_QUALITY_SET_INCLUDED")
        (
            distance_m,
            pool_length_m,
            stroke,
            planned_role,
            planned_intensity,
            target_min_pace,
            target_max_pace,
            repetitions,
            pace_basis,
            signature_planned_rest,
        ) = signature
        trends.append(
            {
                "signature": {
                    "distance_m": distance_m,
                    "pool_length_m": pool_length_m,
                    "stroke": stroke,
                    "planned_role": planned_role,
                    "planned_intensity": planned_intensity,
                    "target_min_pace_s_per_100m": _number(target_min_pace),
                    "target_max_pace_s_per_100m": _number(target_max_pace),
                    "repetitions": repetitions,
                    "pace_basis": pace_basis,
                    "planned_rest_duration_s": (_number(signature_planned_rest)),
                },
                "session_count": len(observations),
                "first_started_at_utc": observations[0]["started_at_utc"].isoformat(),
                "latest_started_at_utc": observations[-1]["started_at_utc"].isoformat(),
                "pace": {
                    "first_mean_s_per_100m": _number(first_pace),
                    "latest_mean_s_per_100m": _number(latest_pace),
                    "delta_s_per_100m": _delta(latest_pace, first_pace),
                    "interpretation": (
                        "FASTER"
                        if latest_pace < first_pace
                        else "SLOWER"
                        if latest_pace > first_pace
                        else "STABLE"
                    ),
                },
                "consistency": {
                    "first_cv": _number(first_cv if isinstance(first_cv, Decimal) else None),
                    "latest_cv": _number(latest_cv if isinstance(latest_cv, Decimal) else None),
                    "delta_cv": _delta(
                        latest_cv if isinstance(latest_cv, Decimal) else None,
                        first_cv if isinstance(first_cv, Decimal) else None,
                    ),
                },
                "fade": {
                    "first_percent": _number(
                        first_fade if isinstance(first_fade, Decimal) else None
                    ),
                    "latest_percent": _number(
                        latest_fade if isinstance(latest_fade, Decimal) else None
                    ),
                    "delta_percentage_points": _delta(
                        latest_fade if isinstance(latest_fade, Decimal) else None,
                        first_fade if isinstance(first_fade, Decimal) else None,
                    ),
                },
                "actual_rest": {
                    "first_total_s": _number(
                        first_rest if isinstance(first_rest, Decimal) else None
                    ),
                    "latest_total_s": _number(
                        latest_rest if isinstance(latest_rest, Decimal) else None
                    ),
                    "delta_s": _delta(
                        latest_rest if isinstance(latest_rest, Decimal) else None,
                        first_rest if isinstance(first_rest, Decimal) else None,
                    ),
                },
                "stroke_efficiency": {
                    "context_basis": "swim_pace_band",
                    "first_strokes_per_length": _number(first_strokes),
                    "latest_strokes_per_length": _number(latest_strokes),
                    "delta_strokes_per_length": _delta(latest_strokes, first_strokes),
                    "first_swolf": _number(first_swolf),
                    "latest_swolf": _number(latest_swolf),
                    "delta_swolf": _delta(latest_swolf, first_swolf),
                },
                "rpe": {
                    "first": _number(first_rpe),
                    "latest": _number(latest_rpe),
                    "delta": _delta(latest_rpe, first_rpe),
                },
                "confidence": {"level": confidence, "reasons": reasons},
            }
        )
    trends.sort(
        key=lambda item: (
            -(_integer(item.get("session_count")) or 0),
            str(item["signature"]),
        )
    )
    return trends
