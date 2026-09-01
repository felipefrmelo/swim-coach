import hashlib
import json
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest
from hypothesis import given
from hypothesis import strategies as st

from swim_coach.domain.activities import (
    NormalizedActivity,
    SessionFeedback,
    analyze_swim,
    coefficient_of_variation,
    completion_ratio,
    fade_percent,
    pace_seconds_per_100m,
    srpe_load,
)
from swim_coach.domain.shared.value_objects import EntityId, UserId
from swim_coach.domain.workouts import CanonicalWorkout
from swim_coach.infrastructure.fit import GarminFitActivityParser

GARMIN_FIXTURE = Path(__file__).parents[1] / "fixtures" / "garmin" / "pool_swim_860m_sanitized.json"


def _regression_case() -> tuple[NormalizedActivity, CanonicalWorkout, UserId]:
    fixture = json.loads(GARMIN_FIXTURE.read_text())
    assert fixture["evidence_status"] == "MIXED_DOCUMENTED_AND_INFERRED"
    assert fixture["source_fit_available_during_fixture_creation"] is True
    assert fixture["raw_fit_versioned"] is False
    assert fixture["evidence"]["fit_messages"]["source"] == "DECODED_FIT"
    assert fixture["evidence"]["fit_messages"]["interpretation"] == "DOCUMENTED"
    assert fixture["evidence"]["connect_summary_observation"]["interpretation"] == "INFERRED"
    messages = cast(dict[str, list[dict[str, Any]]], fixture["fit_messages"])
    sessions = messages["session_mesgs"]
    assert len(sessions) == 1
    assert "total_moving_time" not in sessions[0]
    # The real timestamp is intentionally not part of the fixture. A fixed,
    # synthetic origin is sufficient because FIT message indices own lengths.
    started_at = datetime.fromisoformat("2000-01-01T12:00:00+00:00")
    user_id = UserId.new()
    normalized = GarminFitActivityParser().normalize_messages(
        {
            **messages,
            "session_mesgs": [{**sessions[0], "start_time": started_at}],
        },
        user_id=user_id,
        activity_id=EntityId.new(),
        artifact_id=EntityId.new(),
        input_checksum=hashlib.sha256(b"analysis-regression").hexdigest(),
        fallback_pool_length_m=25,
    )
    return normalized, CanonicalWorkout.model_validate(fixture["planned_workout"]), user_id


def test_real_fit_fixture_is_sanitized_and_keeps_sources_separate() -> None:
    fixture = json.loads(GARMIN_FIXTURE.read_text())
    serialized = json.dumps(fixture, sort_keys=True).lower()

    assert "_activity.fit" not in serialized
    assert '"start_time":' not in serialized
    assert '"checksum":' not in serialized
    assert '"activityid":' not in serialized
    assert fixture["privacy"].startswith("The private ZIP/FIT is not versioned.")
    assert fixture["connect_summary_observation"]["movingDuration"] == 1699.541
    fit_messages = fixture["fit_messages"]
    session = fit_messages["session_mesgs"][0]
    assert "total_moving_time" not in session
    assert session == {
        "sport": "swimming",
        "sub_sport": "lap_swimming",
        "total_elapsed_time": 2089.629,
        "total_timer_time": 2075.559,
        "total_distance": 860,
        "enhanced_avg_speed": 0.506,
        "pool_length": 20,
        "pool_length_unit": "metric",
        "num_active_lengths": 43,
        "workout_rpe": 30,
        "workout_feel": 75,
    }
    active_lengths = [
        item for item in fit_messages["length_mesgs"] if item["length_type"] == "active"
    ]
    idle_lengths = [item for item in fit_messages["length_mesgs"] if item["length_type"] == "idle"]
    assert len(active_lengths) == 43
    assert len(idle_lengths) == 18
    assert sum(Decimal(str(item["total_timer_time"])) for item in active_lengths) == Decimal(
        "1699.541"
    )
    assert sum(Decimal(str(item["total_timer_time"])) for item in idle_lengths) == Decimal(
        "376.018"
    )
    laps = fit_messages["lap_mesgs"]
    assert len(laps) == 28
    assert sum(
        Decimal(str(item["total_timer_time"])) for item in laps if item["total_distance"] > 0
    ) == Decimal("1807.915")
    assert sum(
        Decimal(str(item["total_timer_time"])) for item in laps if item["total_distance"] == 0
    ) == Decimal("267.644")
    assert len(fit_messages["workout_step_mesgs"]) == 13
    assert fixture["derived_cross_checks"] == {
        "active_length_count": 43,
        "idle_length_count": 18,
        "active_length_timer_sum_s": 1699.541,
        "idle_length_timer_sum_s": 376.018,
        "all_length_timer_sum_s": 2075.559,
        "positive_distance_lap_timer_sum_s": 1807.915,
        "zero_distance_lap_timer_sum_s": 267.644,
        "elapsed_minus_timer_s": 14.07,
        "active_lengths_times_pool_length_m": 860,
        "connect_moving_equals_active_length_timer_sum": True,
        "interpretation": "DERIVED_FROM_DECODED_FIT_AND_CONNECT_OBSERVATION",
    }


def test_normative_activity_formulas() -> None:
    assert pace_seconds_per_100m(Decimal(2700), 2000) == Decimal("135.000")
    assert completion_ratio(2100, 2000) == Decimal("1.050")
    assert srpe_load(Decimal(2700), 6) == Decimal("270.00")
    assert srpe_load(Decimal(2700), Decimal("0")) == Decimal("0.00")
    assert coefficient_of_variation((Decimal(100), Decimal(110))) == Decimal("0.0476")
    assert fade_percent(
        (Decimal(100), Decimal(100), Decimal(102), Decimal(104), Decimal(110), Decimal(110))
    ) == Decimal("10.00")


@given(
    duration=st.decimals(min_value=0, max_value=100_000, allow_nan=False),
    distance=st.integers(min_value=0, max_value=100_000),
)
def test_pace_never_divides_by_zero(duration: Decimal, distance: int) -> None:
    result = pace_seconds_per_100m(duration, distance)
    assert result is None if distance == 0 else result is not None and result >= 0


def test_invalid_metric_inputs_fail_closed() -> None:
    with pytest.raises(ValueError):
        pace_seconds_per_100m(Decimal(-1), 20)
    with pytest.raises(ValueError):
        srpe_load(Decimal(60), 11)


def test_real_860m_case_uses_explicit_semantics_and_contextual_work_analysis() -> None:
    normalized, workout, user_id = _regression_case()
    feedback = SessionFeedback(
        id=EntityId.new(),
        user_id=user_id,
        activity_id=normalized.normalization.activity_id,
        rpe=6,
    )

    analysis = analyze_swim(
        normalized,
        user_id=user_id,
        analysis_version="test:2",
        planned_workout_id=EntityId.new(),
        planned_distance_m=880,
        planned_workout=workout,
        feedback=feedback,
    )
    metrics = cast(dict[str, Any], analysis.metrics)

    assert normalized.normalization.pool_length_m == 20
    assert normalized.normalization.distance_m == 860
    assert normalized.normalization.active_length_count == 43
    assert normalized.normalization.perceived_effort_rpe == Decimal("3.0")
    assert normalized.normalization.feeling_score == 75
    assert normalized.normalization.moving_seconds is None
    assert normalized.normalization.swim_seconds == Decimal("1699.541")
    assert normalized.normalization.rest_seconds == Decimal("376.018")
    assert sum(item.length_type == "active" for item in normalized.lengths) == 43
    assert sum(item.length_type == "idle" for item in normalized.lengths) == 18
    assert metrics["durations"] == {
        "elapsed_s": "2089.629",
        "timer_s": "2075.559",
        "moving_s": None,
        "swim_s": "1699.541",
        "rest_s": "376.018",
        "stationary_s": None,
    }
    assert metrics["paces"]["moving_s_per_100m"] is None
    assert metrics["paces"]["swim_s_per_100m"] == "197.621"
    assert metrics["paces"]["timer_s_per_100m"] == "241.344"
    assert metrics["paces"]["pace_from_garmin_reported_speed_s_per_100m"] == "197.628"
    assert metrics["total_rest_seconds"] == "376.018"
    assert "REST_CLASSIFIED_FROM_PLANNED_WORKOUT" not in analysis.flags
    assert "REST_CLASSIFIED_FROM_PLANNED_WORKOUT" not in metrics["data_quality"]["reasons"]
    first_main = normalized.intervals[9]
    assert first_main.timer_seconds == Decimal("158.171")
    assert first_main.swim_seconds == Decimal("135.171")
    assert first_main.garmin_reported_speed_m_per_s == Decimal("0.592")
    assert first_main.pace_from_garmin_reported_speed_seconds_per_100m == Decimal("168.919")
    assert first_main.timer_pace_seconds_per_100m == Decimal("197.714")
    assert first_main.swim_pace_seconds_per_100m == Decimal("168.964")
    assert metrics["planned_vs_actual"]["planned_distance_m"] == 880
    assert metrics["planned_vs_actual"]["actual_distance_m"] == 860
    assert metrics["planned_vs_actual"]["distance_difference_m"] == -20
    assert metrics["planned_vs_actual"]["unmatched_actual_indices"] == [26, 27]
    assert metrics["contextual_paces"]["drill"]["swim"]["distance_m"] == 0
    # Prescribed freestyle contextualizes indeterminate MIXED detections, while
    # the explicit breaststroke mismatch remains excluded from freestyle work.
    assert metrics["contextual_paces"]["freestyle_work"]["swim"]["distance_m"] == 240
    assert metrics["contextual_paces"]["freestyle_work"]["quality"] == {
        "level": "MEDIUM",
        "reasons": ["PLANNED_STROKE_CONTEXT_USED"],
    }
    assert any(length.timer_seconds == Decimal("72.770") for length in normalized.lengths)
    main_set = next(item for item in metrics["sets"] if item["key"]["set_id"] == "main-4x80")
    assert len(main_set["paces_s_per_100m"]) == 4
    assert main_set["key"]["stroke"] == "MIXED"
    assert main_set["key"]["planned_intensity"] is None
    assert main_set["key"]["target_min_pace_s_per_100m"] is None
    assert main_set["key"]["target_max_pace_s_per_100m"] is None
    assert main_set["pace_basis"] == "swim"
    assert main_set["paces_s_per_100m"] == ["168.964", "194.359", "178.626", "174.990"]
    assert main_set["mean_pace_s_per_100m"] == "179.235"
    assert main_set["target_compliance_pace_basis"] is None
    assert main_set["planned_rest_duration_s"] == "100.000"
    assert main_set["actual_rest_duration_s"] == "100.121"
    assert main_set["quality"] == "MEDIUM"
    short_set = next(item for item in metrics["sets"] if item["key"]["set_id"] == "work-4x40")
    assert short_set["interval_indices"] == [19, 21, 23]
    assert 17 not in short_set["interval_indices"]
    prescribed_freestyle = next(
        item for item in metrics["sets"] if item["key"]["set_id"] == "work-2x40-pairs"
    )
    assert prescribed_freestyle["key"]["stroke"] == "FREESTYLE"
    assert prescribed_freestyle["interval_indices"] == [1, 3, 7]
    assert prescribed_freestyle["excluded_outlier_indices"] == []
    assert prescribed_freestyle["excluded_stroke_mismatch_indices"] == [5]
    assert "DETECTED_STROKE_MISMATCH_EXCLUDED" in prescribed_freestyle["quality_reasons"]
    assert "PLANNED_STROKE_CONTEXT_USED" in prescribed_freestyle["quality_reasons"]
    assert metrics["set_pace_basis"] == "per_set_explicit"
    assert metrics["profile_pace_basis"] == "swim"
    efficiency_groups = cast(list[dict[str, Any]], metrics["stroke_efficiency"])
    assert efficiency_groups
    assert all("planned_role" in item and "pace_context" in item for item in efficiency_groups)
    assert all("quality" in item for item in efficiency_groups)
    assert all("stroke_count_sample_count" in item for item in efficiency_groups)
    assert all("swolf_sample_count" in item for item in efficiency_groups)
    assert len(
        {
            (
                item["stroke"],
                item["length_distance_m"],
                item["planned_role"],
                json.dumps(item["pace_context"], sort_keys=True),
            )
            for item in efficiency_groups
        }
    ) == len(efficiency_groups)
    suspicious = next(
        item for item in normalized.lengths if item.timer_seconds == Decimal("72.770")
    )
    assert suspicious.detected_stroke == "breaststroke"
    suspicious_alignment = next(
        item for item in metrics["planned_vs_actual"]["alignments"] if item["actual_index"] == 17
    )
    assert suspicious_alignment["status"] == "PARTIAL"
    assert suspicious_alignment["confidence"] == "0.7250"
    assert suspicious_alignment["planned_distance_m"] == 40
    assert suspicious_alignment["actual_distance_m"] == 20
    assert suspicious_alignment["distance_difference_m"] == -20
    assert suspicious_alignment["reasons"] == ["DISTANCE_MISMATCH"]
    main_alignments = [
        item
        for item in metrics["planned_vs_actual"]["alignments"]
        if item["set_id"] == "main-4x80" and item["planned_role"] == "WORK"
    ]
    assert all(item["planned_duration_s"] is None for item in main_alignments)
    assert all(item["planned_duration_min_s"] is None for item in main_alignments)
    assert all(item["planned_duration_max_s"] is None for item in main_alignments)
    assert all(item["actual_duration_basis"] == "timer_duration_s" for item in main_alignments)
    assert all(item["planned_pace_basis"] is None for item in main_alignments)
    assert metrics["srpe"]["duration_basis"] == "timer_duration_s"
    assert metrics["srpe"]["duration_s"] == "2075.559"
    assert metrics["srpe"]["rpe"] == "6"
    assert metrics["srpe"]["rpe_source"] == "MANUAL_OVERRIDE"
    assert metrics["session_evaluation"] == {
        "garmin": {"rpe": "3.0", "feeling_score": 75},
        "manual_override": {"rpe": 6, "feeling_score": None},
        "effective": {
            "rpe": "6",
            "feeling_score": 75,
        },
        "provenance": {
            "rpe": {"source": "MANUAL_OVERRIDE"},
            "feeling_score": {"source": "GARMIN"},
        },
    }


def test_garmin_evaluation_drives_srpe_when_manual_feedback_is_absent() -> None:
    normalized, workout, user_id = _regression_case()

    analysis = analyze_swim(
        normalized,
        user_id=user_id,
        analysis_version="test:garmin-evaluation",
        planned_workout=workout,
    )

    assert analysis.metrics["srpe"] == {
        "load": "103.78",
        "rpe": "3.0",
        "rpe_source": "GARMIN",
        "duration_basis": "timer_duration_s",
        "duration_s": "2075.559",
    }
    assert analysis.metrics["srpe_load"] is None


def test_analysis_length_overlay_preserves_stationary_continuity_boundaries() -> None:
    normalized, workout, user_id = _regression_case()
    lengths = tuple(
        replace(item, stationary_seconds=Decimal("0.001")) if item.length_type == "active" else item
        for item in normalized.lengths
    )

    analysis = analyze_swim(
        NormalizedActivity(
            normalized.normalization, normalized.laps, normalized.intervals, lengths
        ),
        user_id=user_id,
        analysis_version="test:stationary-continuity",
        planned_workout=workout,
        goal_pace_s_per_100m=Decimal("1000"),
    )
    metrics = cast(dict[str, Any], analysis.metrics)

    assert metrics["continuity"]["longest_continuous_swim"]["distance_m"] == 20
    assert metrics["continuity"]["best_windows"]["100"] is None
    assert metrics["longest_distance_below_goal_pace"]["distance_m"] == 20


def test_interval_stationary_without_length_location_prevents_inflated_continuity() -> None:
    normalized, workout, user_id = _regression_case()
    intervals = tuple(
        replace(item, stationary_seconds=Decimal("1")) if item.distance_m > 0 else item
        for item in normalized.intervals
    )
    lengths = tuple(replace(item, stationary_seconds=None) for item in normalized.lengths)

    analysis = analyze_swim(
        NormalizedActivity(normalized.normalization, normalized.laps, intervals, lengths),
        user_id=user_id,
        analysis_version="test:interval-stationary-continuity",
        planned_workout=workout,
        goal_pace_s_per_100m=Decimal("1000"),
    )
    metrics = cast(dict[str, Any], analysis.metrics)

    assert metrics["continuity"]["longest_continuous_swim"]["distance_m"] == 20
    assert metrics["continuity"]["best_windows"]["100"] is None
    assert "INTERVAL_STATIONARY_LOCATION_UNKNOWN" in metrics["continuity"]["quality_reasons"]
    assert "INTERVAL_STATIONARY_LOCATION_UNKNOWN" in metrics["data_quality"]["reasons"]
    assert metrics["goal_readiness"]["longest_evidence_distance_m"] == 20
    assert (
        "STATIONARY_INTERVAL_EXCLUDED_FROM_CONTINUOUS_READINESS"
        in metrics["goal_readiness"]["reasons"]
    )
    assert metrics["longest_distance_below_goal_pace"]["distance_m"] == 20


def test_planned_rest_can_contextualize_unknown_zero_distance_intervals() -> None:
    normalized, workout, user_id = _regression_case()
    intervals = tuple(
        replace(item, interval_type="unknown", rest_seconds=Decimal(0))
        if item.distance_m == 0
        else item
        for item in normalized.intervals
    )
    contextual = NormalizedActivity(
        replace(normalized.normalization, rest_seconds=Decimal(0)),
        normalized.laps,
        intervals,
        normalized.lengths,
    )

    analysis = analyze_swim(
        contextual,
        user_id=user_id,
        analysis_version="test:planned-rest",
        planned_workout=workout,
        planned_distance_m=880,
    )
    metrics = cast(dict[str, Any], analysis.metrics)

    assert Decimal(metrics["total_rest_seconds"]) > 0
    assert "REST_CLASSIFIED_FROM_PLANNED_WORKOUT" in analysis.flags
    aligned_rests = [
        item
        for item in metrics["planned_vs_actual"]["alignments"]
        if item["planned_interval_type"] == "REST" and item["actual_index"] is not None
    ]
    assert aligned_rests
