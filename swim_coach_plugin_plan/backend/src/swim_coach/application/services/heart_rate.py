"""HR of main repetitions and bounded, explicitly exploratory historical comparisons."""

from collections.abc import Mapping, Sequence
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from swim_coach.domain.activities.heart_rate import valid_bpm


def _decimal(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() and result >= 0 else None


def _number(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f")


def main_block_heart_rate(view: Mapping[str, Any]) -> dict[str, Any]:
    """Weight available lap averages by timer duration, with measured-time coverage.

    A FIT lap average is not a sample-level swimming-only average. We keep its
    timer scope explicit, even when the pace uses moving or swim duration.
    """
    blocks: list[dict[str, Any]] = []
    covered = total = weighted = Decimal(0)
    previous_rest: Decimal | None = None
    excluded_indices: set[int] = set()
    analysis = view.get("analysis")
    if isinstance(analysis, Mapping):
        metrics = analysis.get("metrics", {})
        for outlier in metrics.get("outliers", []):
            if isinstance(outlier, Mapping) and isinstance(outlier.get("interval_index"), int):
                excluded_indices.add(outlier["interval_index"])
    for interval in view.get("intervals", []):
        durations = interval["durations"]
        if interval["interval_type"] == "REST" or interval["planned_role"] == "REST":
            previous_rest = _decimal(durations.get("timer_s"))
            continue
        if interval["interval_type"] != "SWIM" or interval["planned_role"] != "WORK":
            previous_rest = None
            continue
        duration = _decimal(durations.get("timer_s"))
        if duration is None or duration <= 0:
            previous_rest = None
            continue
        hr = interval["heart_rate"]
        avg = valid_bpm(hr.get("avg_bpm"))
        maximum = valid_bpm(hr.get("max_bpm"))
        if avg is not None and maximum is not None and avg > maximum:
            avg = maximum = None
        total += duration
        if avg is not None:
            covered += duration
            weighted += Decimal(avg) * duration
        basis = "moving" if interval["paces"]["moving_s_per_100m"] is not None else "swim"
        pace = _decimal(interval["paces"].get(f"{basis}_s_per_100m"))
        warnings = list(interval["quality_warnings"])
        if interval["index"] in excluded_indices:
            warnings.append("EXCLUDE_FROM_FITNESS")
        blocks.append(
            {
                "interval_index": interval["index"],
                "distance_m": interval["distance_m"],
                "timer_duration_s": _number(duration),
                "pace_s_per_100m": _number(pace),
                "pace_basis": basis if pace is not None else None,
                "stroke": interval["detected_stroke"],
                "avg_bpm": avg,
                "max_bpm": maximum,
                "rest_before_s": _number(previous_rest),
                "quality_warnings": warnings,
            }
        )
        previous_rest = None
    return {
        "avg_bpm": _number(weighted / covered) if covered > 0 else None,
        "max_bpm": max((b["max_bpm"] for b in blocks if b["max_bpm"] is not None), default=None),
        "weight_basis": "FIT_LAP_AVERAGE_WEIGHTED_BY_TIMER_DURATION",
        "coverage_ratio": _number(covered / total) if total > 0 else None,
        "covered_timer_s": _number(covered),
        "total_timer_s": _number(total),
        "blocks": blocks,
        "warnings": ["LAP_HR_MAY_INCLUDE_STATIONARY_TIME"]
        + (
            ["MAIN_BLOCKS_UNAVAILABLE"]
            if not blocks
            else ["MAIN_HR_PARTIAL_OR_UNAVAILABLE"]
            if covered < total
            else []
        ),
    }


def aerobic_comparisons(
    current: Mapping[str, Any],
    history: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Pair main repetitions at a similar pace; never infer fitness from HR alone."""
    comparisons: list[dict[str, Any]] = []

    def eligible(view: Mapping[str, Any]) -> bool:
        return (
            view.get("normalization") is not None
            and view.get("data_quality", {}).get("level") != "LOW"
            and not view.get("execution_evidence", {}).get("performance_blocked")
        )

    def usable(block: Mapping[str, Any]) -> bool:
        return (
            block.get("avg_bpm") is not None
            and (_decimal(block.get("pace_s_per_100m")) or Decimal(0)) > 0
            and block.get("stroke") not in (None, "unknown", "mixed", "drill")
            and not block.get("quality_warnings")
        )

    if eligible(current):
        for block in current.get("main_set_heart_rate", {}).get("blocks", []):
            if not usable(block):
                continue
            pace = Decimal(block["pace_s_per_100m"])
            candidates = []
            for prior in history:
                if not eligible(prior) or prior["pool"]["length_m"] != current["pool"]["length_m"]:
                    continue
                if current["pool"]["length_m"] is None:
                    continue
                for earlier in prior.get("main_set_heart_rate", {}).get("blocks", []):
                    if not usable(earlier) or earlier["stroke"] != block["stroke"]:
                        continue
                    if earlier["pace_basis"] != block["pace_basis"]:
                        continue
                    pace_gap = abs(pace - Decimal(earlier["pace_s_per_100m"]))
                    if pace_gap <= Decimal(3):
                        candidates.append((pace_gap, prior, earlier))
            if not candidates:
                continue
            # Prefer closest pace. Input history is most recent first for equal gaps.
            _, prior, earlier = min(candidates, key=lambda candidate: candidate[0])
            reasons = ["SINGLE_PAIR_NOT_A_FITNESS_TREND", "LAP_HR_SCOPE", "SENSOR_UNVERIFIED"]
            if block["distance_m"] != earlier["distance_m"]:
                reasons.append("DIFFERENT_REPETITION_DISTANCE_AND_HR_RESPONSE_TIME")
            if block["rest_before_s"] is None or earlier["rest_before_s"] is None:
                reasons.append("RECOVERY_CONTEXT_UNAVAILABLE")
            elif block["rest_before_s"] != earlier["rest_before_s"]:
                reasons.append("DIFFERENT_PRECEDING_REST")
            comparisons.append(
                {
                    "current_activity_id": current["activity_id"],
                    "previous_activity_id": prior["activity_id"],
                    "current_started_at_utc": current["started_at_utc"],
                    "previous_started_at_utc": prior["started_at_utc"],
                    "current": block,
                    "previous": earlier,
                    "delta_avg_bpm": block["avg_bpm"] - earlier["avg_bpm"],
                    "delta_pace_s_per_100m": _number(pace - Decimal(earlier["pace_s_per_100m"])),
                    "confidence": "LOW",
                    "comparison_type": "EXPLORATORY",
                    "reasons": reasons,
                }
            )
            if len(comparisons) >= 10:
                break
    return {
        "status": "AVAILABLE" if comparisons else "INSUFFICIENT_COMPARABLE_DATA",
        "pace_tolerance_s_per_100m": 3,
        "history_limit": 20,
        "items": comparisons,
        "guidance": "Lower HR at similar pace is descriptive evidence, not proof of aerobic "
        "improvement. Review repetition duration, recovery, sensor, RPE and repeated sessions.",
    }
