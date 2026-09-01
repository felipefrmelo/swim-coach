"""Versioned public activity views built only from canonical facts."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from swim_coach.application.services.activity_data import ActivityDetail
from swim_coach.domain.activities import (
    ActivityNormalization,
    NormalizedActivity,
    SessionEvaluationSource,
    SessionFeedback,
    resolve_session_evaluation,
)
from swim_coach.domain.garmin import Activity

_LEGACY_NORMALIZER_MARKER = "|swim-coach:1."
_V1_ANALYSIS_METRIC_KEYS = frozenset(
    {
        "average_pace_seconds_per_100m",
        "best_interval_pace_seconds_per_100m",
        "total_rest_seconds",
        "consistency_cv",
        "fade_percent",
        "completion_ratio",
        "average_swolf",
        "average_strokes_per_length",
        "srpe_load",
        "pool_length_m",
    }
)
_V2_ANALYSIS_METRIC_KEYS = frozenset(
    {
        "distance_m",
        "durations",
        "paces",
        "contextual_paces",
        "set_pace_basis",
        "profile_pace_basis",
        "sets",
        "outliers",
        "continuity",
        "longest_distance_below_goal_pace",
        "speed_endurance",
        "goal_readiness",
        "planned_vs_actual",
        "stroke_efficiency",
        "session_evaluation",
        "srpe",
        "data_quality",
        "active_length_count",
        "completeness",
    }
)
_V2_ANALYSIS_SUMMARY_KEYS = frozenset(
    {
        "headline",
        "pace_semantics",
        "set_pace_basis",
        "profile_pace_basis",
        "quality",
        "medical_interpretation",
        "css_estimated",
    }
)
_PLANNED_VS_ACTUAL_SUMMARY_KEYS = frozenset(
    {
        "planned_distance_m",
        "actual_distance_m",
        "distance_difference_m",
        "distance_adherence_ratio",
        "matched_step_ratio",
        "mean_alignment_confidence",
        "quality",
    }
)


def _number(value: Decimal | None) -> str | None:
    return format(value, "f") if value is not None else None


def _pace(duration: Decimal | None, distance_m: int) -> Decimal | None:
    if duration is None or distance_m <= 0:
        return None
    return (duration / Decimal(distance_m) * Decimal(100)).quantize(
        Decimal("0.001"), rounding=ROUND_HALF_UP
    )


def _timezone(name: str) -> tuple[str, ZoneInfo, bool]:
    """Resolve an IANA timezone without ever publishing an invalid zone name."""

    try:
        return name, ZoneInfo(name), False
    except (ZoneInfoNotFoundError, ValueError):
        return "UTC", ZoneInfo("UTC"), True


def _normalization_fact(
    normalized: NormalizedActivity | ActivityNormalization | None,
) -> ActivityNormalization | None:
    fact = normalized.normalization if isinstance(normalized, NormalizedActivity) else normalized
    if fact is not None and _LEGACY_NORMALIZER_MARKER in fact.parser_version:
        return None
    return fact


def _canonical_normalized(normalized: NormalizedActivity | None) -> NormalizedActivity | None:
    return normalized if _normalization_fact(normalized) is not None else None


def session_evaluation_v2(
    normalized: NormalizedActivity | ActivityNormalization | None,
    feedback: SessionFeedback | None,
) -> dict[str, Any]:
    """Project Garmin facts, field-level overrides and their effective values."""

    normalization = _normalization_fact(normalized)
    evaluation = resolve_session_evaluation(normalization, feedback)

    def provenance(field: str, source: SessionEvaluationSource | None) -> dict[str, Any]:
        if source is SessionEvaluationSource.MANUAL_OVERRIDE:
            return {"source": source.value}
        if source is None or normalization is None:
            return {"source": None}
        raw = normalization.provenance.get(field)
        fact = raw if isinstance(raw, dict) else {}
        return {
            "source": source.value,
            **{
                key: fact[key]
                for key in ("raw_field", "transformation", "interpretation")
                if key in fact and isinstance(fact[key], str)
            },
        }

    return {
        "garmin": {
            "rpe": _number(evaluation.garmin_rpe),
            "feeling_score": evaluation.garmin_feeling_score,
        },
        "manual_override": {
            "rpe": evaluation.manual_rpe,
            "feeling_score": evaluation.manual_feeling_score,
        },
        "effective": {
            "rpe": _number(evaluation.effective_rpe),
            "feeling_score": evaluation.effective_feeling_score,
        },
        "provenance": {
            "rpe": provenance("perceived_effort_rpe", evaluation.rpe_source),
            "feeling_score": provenance("feeling_score", evaluation.feeling_score_source),
        },
    }


def analysis_metrics_v1(metrics: dict[str, Any]) -> dict[str, Any]:
    """Project only the historically published v1 analysis aliases."""

    return {key: value for key, value in metrics.items() if key in _V1_ANALYSIS_METRIC_KEYS}


def analysis_metrics_v2(metrics: dict[str, Any]) -> dict[str, Any]:
    """Project an explicit allowlist of semantic v2 analysis sections."""

    return {key: value for key, value in metrics.items() if key in _V2_ANALYSIS_METRIC_KEYS}


def analysis_summary_v2(summary: dict[str, Any]) -> dict[str, Any]:
    """Project an explicit allowlist of non-sensitive analysis summary facts."""

    return {key: value for key, value in summary.items() if key in _V2_ANALYSIS_SUMMARY_KEYS}


def planned_vs_actual_summary_v2(value: object) -> dict[str, Any] | None:
    """Bound list views to workout-level adherence facts, never step alignments."""

    if not isinstance(value, dict):
        return None
    return {key: item for key, item in value.items() if key in _PLANNED_VS_ACTUAL_SUMMARY_KEYS}


def _summary_provenance(activity: Activity) -> dict[str, Any]:
    """Describe the source adapter facts without reading or exposing the raw payload."""

    if activity.normalization_version != "garmin-summary-v2":
        return {}
    endpoint = "/activitylist-service/activities/search/activities"
    return {
        "started_at_utc": {
            "source": "garmin",
            "raw_field": "startTimeGMT",
            "interpretation": "inferred",
            "source_endpoint": endpoint,
        },
        "started_at_local": {
            "source": "derived",
            "transformation": "started_at_utc converted with athlete IANA timezone",
        },
        "distance_m": {
            "source": "garmin",
            "raw_field": "distance",
            "interpretation": "inferred",
            "source_endpoint": endpoint,
        },
        "elapsed_duration_s": {
            "source": "inferred",
            "raw_field_candidates": ["elapsedDuration", "duration"],
            "transformation": "activity-list adapter with explicit fallback",
            "interpretation": "inferred",
            "source_endpoint": endpoint,
        },
        "timer_duration_s": {
            "source": "inferred",
            "raw_field_candidates": ["duration", "elapsedDuration"],
            "transformation": "activity-list adapter with explicit fallback",
            "interpretation": "inferred",
            "source_endpoint": endpoint,
        },
        "moving_duration_s": {
            "source": "inferred",
            "value_status": "unavailable_until_canonical_fit_normalization",
        },
        "pool_length_m": {
            "source": "inferred",
            "raw_field": "poolLength",
            "transformation": "activity-list poolLength / 100",
            "interpretation": "inferred",
            "source_endpoint": endpoint,
        },
        "garmin_summary_averagePace": {
            "source": "garmin",
            "raw_field": "averagePace",
            "interpretation": "inferred",
            "source_endpoint": endpoint,
            "value_status": "preserved_private_not_normalized_to_pace",
        },
        "timer_pace_s_per_100m": {
            "source": "derived",
            "transformation": "timer_duration_s / distance_m * 100",
        },
        "session_pace_s_per_100m": {
            "source": "derived",
            "transformation": "elapsed_duration_s / distance_m * 100",
        },
    }


def _quality(
    normalized: NormalizedActivity | ActivityNormalization | None,
    *,
    extra_reasons: tuple[str, ...] = (),
) -> dict[str, Any]:
    normalization = _normalization_fact(normalized)
    if normalization is None:
        reason = (
            "LEGACY_NORMALIZATION_NOT_CANONICAL_V2"
            if normalized is not None
            else "FIT_NORMALIZATION_UNAVAILABLE"
        )
        return {"level": "LOW", "reasons": list(dict.fromkeys((reason, *extra_reasons)))}
    raw = normalization.quality.value
    level = {"complete": "HIGH", "partial": "MEDIUM", "poor": "LOW"}.get(raw, "LOW")
    if extra_reasons and level == "HIGH":
        level = "MEDIUM"
    return {
        "level": level,
        "reasons": list(dict.fromkeys((*normalization.warnings, *extra_reasons))),
    }


def activity_summary_v2(
    activity: Activity,
    normalized: NormalizedActivity | ActivityNormalization | None = None,
    *,
    timezone_name: str | None = None,
    feedback: SessionFeedback | None = None,
) -> dict[str, Any]:
    normalization = _normalization_fact(normalized)
    requested_zone_name = timezone_name or activity.timezone
    zone_name, zone, invalid_timezone = _timezone(requested_zone_name)
    local_started = activity.start_time_utc.astimezone(zone)
    distance_m = normalization.distance_m if normalization else activity.distance.meters
    elapsed = normalization.elapsed_seconds if normalization else activity.elapsed.seconds
    timer = normalization.timer_seconds if normalization else activity.timer.seconds
    # Legacy activity rows cannot distinguish a missing Garmin moving duration
    # from the historic timer fallback. Only canonical normalization may expose it.
    moving = normalization.moving_seconds if normalization else None
    swim = normalization.swim_seconds if normalization else None
    rest = normalization.rest_seconds if normalization else None
    stationary = normalization.stationary_seconds if normalization else None
    summary_pool_length = (
        None
        if activity.normalization_version == "garmin-summary-v1"
        else activity.pool_length.meters
        if activity.pool_length
        else None
    )
    pool_length = normalization.pool_length_m if normalization else summary_pool_length
    provenance = dict(normalization.provenance) if normalization else _summary_provenance(activity)
    if invalid_timezone:
        provenance["timezone"] = {
            "source": "inferred",
            "transformation": "invalid IANA timezone replaced with UTC",
            "warning": "INVALID_TIMEZONE_FALLBACK_UTC",
        }
        provenance["started_at_local"] = {
            "source": "derived",
            "transformation": "started_at_utc converted with UTC fallback",
        }
    return {
        "activity_id": str(activity.id),
        "name": activity.name,
        "subtype": activity.subtype,
        "started_at_utc": activity.start_time_utc.isoformat(),
        "started_at_local": local_started.isoformat(),
        "timezone": zone_name,
        "distance_m": distance_m,
        "durations": {
            "elapsed_s": _number(elapsed),
            "timer_s": _number(timer),
            "moving_s": _number(moving),
            "swim_s": _number(swim),
            "rest_s": _number(rest),
            "stationary_s": _number(stationary),
        },
        "speeds": {
            "garmin_reported_m_per_s": _number(
                normalization.garmin_reported_speed_m_per_s if normalization else None
            ),
        },
        "paces": {
            "pace_from_garmin_reported_speed_s_per_100m": _number(
                normalization.pace_from_garmin_reported_speed_seconds_per_100m
                if normalization
                else None
            ),
            "moving_s_per_100m": _number(
                normalization.moving_pace_seconds_per_100m
                if normalization
                else _pace(moving, distance_m)
            ),
            "swim_s_per_100m": _number(
                normalization.swim_pace_seconds_per_100m if normalization else None
            ),
            "timer_s_per_100m": _number(
                normalization.timer_pace_seconds_per_100m
                if normalization
                else _pace(timer, distance_m)
            ),
            "session_s_per_100m": _number(
                normalization.session_pace_seconds_per_100m
                if normalization
                else _pace(elapsed, distance_m)
            ),
        },
        "pool": {
            "length_m": pool_length,
            "active_length_count": (
                normalization.active_length_count if normalization else activity.length_count
            ),
        },
        "provenance": provenance,
        "data_quality": _quality(
            normalized,
            extra_reasons=("INVALID_TIMEZONE_FALLBACK_UTC",) if invalid_timezone else (),
        ),
        "session_evaluation": session_evaluation_v2(normalized, feedback),
    }


def activity_detail_v2(
    detail: ActivityDetail, *, timezone_name: str | None = None
) -> dict[str, Any]:
    normalized = _canonical_normalized(detail.normalized)
    analysis = (
        detail.analysis
        if normalized is not None
        and detail.analysis is not None
        and detail.analysis.normalization_id == normalized.normalization.id
        else None
    )
    result = activity_summary_v2(
        detail.activity,
        detail.normalized,
        timezone_name=timezone_name,
        feedback=detail.feedback,
    )
    alignment_by_actual: dict[int, dict[str, Any]] = {}
    if analysis:
        planned_actual = analysis.metrics.get("planned_vs_actual")
        if isinstance(planned_actual, dict):
            alignments = planned_actual.get("alignments")
            if isinstance(alignments, list):
                for item in alignments:
                    if not isinstance(item, dict):
                        continue
                    actual_index = item.get("actual_index")
                    if isinstance(actual_index, int) and not isinstance(actual_index, bool):
                        alignment_by_actual[actual_index] = item
        analysis_quality = analysis.metrics.get("data_quality")
        if isinstance(analysis_quality, dict):
            level = analysis_quality.get("level")
            reasons = analysis_quality.get("reasons")
            if isinstance(level, str) and isinstance(reasons, list):
                result["data_quality"] = {"level": level, "reasons": reasons}
    result.update(
        {
            "schema_version": "2.0",
            "normalization": (
                {
                    "parser_version": normalized.normalization.parser_version,
                    "profile_version": normalized.normalization.profile_version,
                    "completeness": _number(normalized.normalization.completeness),
                    "warnings": list(normalized.normalization.warnings),
                }
                if normalized
                else None
            ),
            "intervals": [
                _interval(item, alignment_by_actual.get(item.interval_index))
                for item in normalized.intervals
            ]
            if normalized
            else [],
            "lengths": [_length(item) for item in normalized.lengths] if normalized else [],
            "analysis": (
                {
                    "version": analysis.analysis_version,
                    "quality": analysis.quality.value,
                    "metrics": analysis_metrics_v2(dict(analysis.metrics)),
                    "flags": list(analysis.flags),
                    "summary": analysis_summary_v2(dict(analysis.summary)),
                }
                if analysis
                else None
            ),
            "match": (
                {
                    "planned_workout_id": str(detail.match.planned_workout_id),
                    "confidence": _number(detail.match.confidence),
                    "method": detail.match.method,
                }
                if detail.match
                else None
            ),
            "feedback": (
                {
                    "id": str(detail.feedback.id),
                    "rpe": detail.feedback.rpe,
                    "technique_rating": detail.feedback.technique_rating,
                    "fatigue_rating": detail.feedback.fatigue_rating,
                    "enjoyment_rating": detail.feedback.enjoyment_rating,
                    "feeling_score": detail.feedback.feeling_score,
                    "pain_present": detail.feedback.pain_present,
                    "pain_location": detail.feedback.pain_location,
                    "pain_intensity": detail.feedback.pain_intensity,
                    "comment": detail.feedback.comment,
                    "version": detail.feedback.version,
                    "updated_at": detail.feedback.updated_at.isoformat(),
                }
                if detail.feedback
                else None
            ),
            "raw_fit_exposed": False,
        }
    )
    return result


def _interval(item: Any, alignment: dict[str, Any] | None = None) -> dict[str, Any]:
    planned_role = alignment.get("planned_role") if alignment else item.planned_role
    planned_stroke = alignment.get("planned_stroke") if alignment else item.planned_stroke
    interval_type = "SWIM" if item.interval_type == "work" else item.interval_type.upper()
    return {
        "index": item.interval_index,
        "interval_type": interval_type,
        "planned_role": str(planned_role).upper() if planned_role else None,
        "distance_m": item.distance_m,
        "durations": {
            "elapsed_s": _number(item.elapsed_seconds),
            "timer_s": _number(item.timer_seconds),
            "moving_s": _number(item.moving_seconds),
            "swim_s": _number(item.swim_seconds),
            "rest_s": _number(item.rest_seconds),
            "stationary_s": _number(item.stationary_seconds),
        },
        "speeds": {
            "garmin_reported_m_per_s": _number(item.garmin_reported_speed_m_per_s),
        },
        "paces": {
            "pace_from_garmin_reported_speed_s_per_100m": _number(
                item.pace_from_garmin_reported_speed_seconds_per_100m
            ),
            "moving_s_per_100m": _number(item.moving_pace_seconds_per_100m),
            "swim_s_per_100m": _number(item.swim_pace_seconds_per_100m),
            "timer_s_per_100m": _number(item.timer_pace_seconds_per_100m),
            "elapsed_s_per_100m": _number(item.elapsed_pace_seconds_per_100m),
        },
        "detected_stroke": item.detected_stroke,
        "planned_stroke": planned_stroke,
        "stroke_count": item.stroke_count,
        "stroke_rate": _number(item.stroke_rate),
        "swolf": _number(item.swolf),
        "provenance": dict(item.provenance),
        "quality_warnings": list(item.quality_warnings),
    }


def _length(item: Any) -> dict[str, Any]:
    return {
        "index": item.length_index,
        "length_type": item.length_type.upper(),
        "distance_m": item.distance_m,
        "durations": {
            "elapsed_s": _number(item.elapsed_seconds),
            "timer_s": _number(item.timer_seconds),
            "moving_s": _number(item.moving_seconds),
            "swim_s": _number(item.swim_seconds),
            "rest_s": _number(item.rest_seconds),
            "stationary_s": _number(item.stationary_seconds),
        },
        "speeds": {
            "garmin_reported_m_per_s": _number(item.garmin_reported_speed_m_per_s),
        },
        "paces": {
            "pace_from_garmin_reported_speed_s_per_100m": _number(
                item.pace_from_garmin_reported_speed_seconds_per_100m
            ),
            "moving_s_per_100m": _number(item.moving_pace_seconds_per_100m),
            "swim_s_per_100m": _number(item.swim_pace_seconds_per_100m),
            "timer_s_per_100m": _number(item.timer_pace_seconds_per_100m),
            "elapsed_s_per_100m": _number(item.elapsed_pace_seconds_per_100m),
        },
        "detected_stroke": item.detected_stroke,
        "planned_stroke": item.planned_stroke,
        "stroke_count": item.stroke_count,
        "stroke_rate": _number(item.stroke_rate),
        "swolf": _number(item.swolf),
        "provenance": dict(item.provenance),
        "quality_warnings": list(item.quality_warnings),
    }
