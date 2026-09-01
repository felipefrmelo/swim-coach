from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from swim_coach.application.services.equivalent_set_history import (
    historical_equivalent_set_trends,
)


def _set(
    *,
    pace: str,
    pace_basis: str = "swim",
    stroke: str = "FREESTYLE",
    role: str = "WORK",
    intensity: str = "MODERATE",
    target_min: str = "170",
    target_max: str = "190",
    quality: str = "HIGH",
) -> dict[str, Any]:
    return {
        "key": {
            "distance_m": 80,
            "stroke": stroke,
            "planned_role": role,
            "set_id": "session-specific-id",
            "planned_intensity": intensity,
            "target_min_pace_s_per_100m": target_min,
            "target_max_pace_s_per_100m": target_max,
        },
        "pace_basis": pace_basis,
        "paces_s_per_100m": [pace, pace, pace, pace],
        "mean_pace_s_per_100m": pace,
        "coefficient_of_variation": "0.04",
        "fade_percent": "2.0",
        "planned_rest_duration_s": "75",
        "actual_rest_duration_s": "72",
        "quality": quality,
    }


def _metrics(
    *sets: dict[str, Any],
    rpe: int = 6,
    feeling_score: int | None = None,
    session_quality: str = "HIGH",
) -> dict[str, Any]:
    return {
        "pool_length_m": 20,
        "sets": list(sets),
        "data_quality": {"level": session_quality},
        "srpe": {"rpe": rpe, "duration_basis": "timer_duration_s"},
        "session_evaluation": {
            "effective": {
                "rpe": rpe,
                "feeling_score": feeling_score,
            },
            "provenance": {
                "rpe": {"source": "GARMIN"},
                "feeling_score": {"source": "GARMIN" if feeling_score is not None else None},
            },
        },
        "stroke_efficiency": [
            {
                "stroke": "freestyle",
                "planned_role": "WORK",
                "pace_context": {
                    "basis": "swim",
                    "lower_s_per_100m": 180,
                    "upper_exclusive_s_per_100m": 195,
                },
                "average_strokes_per_length": "10",
                "average_swolf": "49",
            }
        ],
    }


def test_history_compares_only_equivalent_sets_across_distinct_sessions() -> None:
    first = datetime(2026, 8, 1, 12, tzinfo=UTC)
    latest = datetime(2026, 8, 8, 12, tzinfo=UTC)
    trends = historical_equivalent_set_trends(
        [
            (first, _metrics(_set(pace="190"), _set(pace="192"), rpe=7, feeling_score=50)),
            (latest, _metrics(_set(pace="185"), rpe=6, feeling_score=75)),
            # Same geometry but a different semantic basis is a different signature.
            (first, _metrics(_set(pace="200", pace_basis="timer"))),
        ]
    )

    assert len(trends) == 1
    trend = trends[0]
    assert trend["signature"] == {
        "distance_m": 80,
        "pool_length_m": 20,
        "stroke": "FREESTYLE",
        "planned_role": "WORK",
        "planned_intensity": "MODERATE",
        "target_min_pace_s_per_100m": 170,
        "target_max_pace_s_per_100m": 190,
        "repetitions": 4,
        "pace_basis": "swim",
        "planned_rest_duration_s": 75,
    }
    assert trend["session_count"] == 2
    assert trend["pace"] == {
        "first_mean_s_per_100m": 191,
        "latest_mean_s_per_100m": 185,
        "delta_s_per_100m": -6,
        "interpretation": "FASTER",
    }
    assert trend["stroke_efficiency"]["latest_swolf"] == 49
    assert trend["rpe"] == {
        "first": 7,
        "latest": 6,
        "delta": -1,
        "first_source": "GARMIN",
        "latest_source": "GARMIN",
    }
    assert trend["feeling"] == {
        "first_score": 50,
        "latest_score": 75,
        "delta": 25,
        "first_source": "GARMIN",
        "latest_source": "GARMIN",
    }


def test_history_requires_two_sessions_and_does_not_mix_roles_or_strokes() -> None:
    first = datetime(2026, 8, 1, 12, tzinfo=UTC)
    latest = datetime(2026, 8, 8, 12, tzinfo=UTC)

    trends = historical_equivalent_set_trends(
        [
            (first, _metrics(_set(pace="190", role="DRILL"))),
            (latest, _metrics(_set(pace="185", stroke="BREASTSTROKE"))),
        ]
    )

    assert trends == []


def test_history_does_not_mix_intensity_or_target_prescription() -> None:
    first = datetime(2026, 8, 1, 12, tzinfo=UTC)
    latest = datetime(2026, 8, 8, 12, tzinfo=UTC)

    intensity_mismatch = historical_equivalent_set_trends(
        [
            (first, _metrics(_set(pace="190", intensity="MODERATE"))),
            (latest, _metrics(_set(pace="170", intensity="FAST"))),
        ]
    )
    target_mismatch = historical_equivalent_set_trends(
        [
            (first, _metrics(_set(pace="190", target_min="170", target_max="190"))),
            (latest, _metrics(_set(pace="180", target_min="160", target_max="180"))),
        ]
    )

    assert intensity_mismatch == []
    assert target_mismatch == []


def test_history_does_not_treat_missing_pace_as_a_missing_repetition() -> None:
    first = datetime(2026, 8, 1, 12, tzinfo=UTC)
    latest = datetime(2026, 8, 8, 12, tzinfo=UTC)
    five_by_eighty = _set(pace="190")
    five_by_eighty["interval_indices"] = [0, 1, 2, 3]
    five_by_eighty["missing_pace_indices"] = [4]
    four_by_eighty = _set(pace="185")
    four_by_eighty["interval_indices"] = [0, 1, 2, 3]
    four_by_eighty["missing_pace_indices"] = []

    trends = historical_equivalent_set_trends(
        [
            (first, _metrics(five_by_eighty)),
            (latest, _metrics(four_by_eighty)),
        ]
    )

    assert trends == []


def test_history_confidence_is_capped_by_session_and_set_quality() -> None:
    starts = [datetime(2026, 8, day, 12, tzinfo=UTC) for day in (1, 8, 15, 22)]

    medium_sessions = historical_equivalent_set_trends(
        [
            (
                start,
                _metrics(_set(pace=str(190 - index)), session_quality="MEDIUM"),
            )
            for index, start in enumerate(starts)
        ]
    )
    low_sets = historical_equivalent_set_trends(
        [
            (start, _metrics(_set(pace=str(190 - index), quality="LOW")))
            for index, start in enumerate(starts)
        ]
    )

    assert medium_sessions[0]["confidence"] == {
        "level": "MEDIUM",
        "reasons": ["MEDIUM_QUALITY_SESSION_INCLUDED"],
    }
    assert low_sets[0]["confidence"] == {
        "level": "LOW",
        "reasons": ["LOW_QUALITY_SET_INCLUDED"],
    }
