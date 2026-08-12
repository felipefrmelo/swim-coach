from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from itertools import pairwise

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from swim_coach.domain.planning import (
    AvailabilitySnapshot,
    ExistingSessionSnapshot,
    FeedbackSnapshot,
    PlanningContext,
    PlanningPreferences,
    PlanningRules,
    RecentWeekSnapshot,
    TrainingRuleSet,
    canonical_json_hash,
    generate_week,
)
from swim_coach.domain.shared.value_objects import EntityId


def ruleset(rules: PlanningRules | None = None) -> TrainingRuleSet:
    selected = rules or PlanningRules()
    return TrainingRuleSet(
        id=EntityId.parse("00000000-0000-0000-0000-000000001010"),
        name="conservative",
        version="1.0.0",
        rules=selected,
        content_hash=canonical_json_hash(selected.model_dump(mode="json")),
        effective_from=date(2026, 8, 10),
        created_at=datetime(2026, 8, 10, tzinfo=UTC),
    )


def context(
    *,
    feedback: tuple[FeedbackSnapshot, ...] = (),
    adherence: float | None = 0.9,
) -> PlanningContext:
    week_start = date(2026, 8, 17)
    return PlanningContext(
        user_id="00000000-0000-0000-0000-000000001001",
        week_start=week_start,
        timezone="America/Sao_Paulo",
        pool_id="00000000-0000-0000-0000-000000001002",
        pool_length_m=20,
        goal_id="00000000-0000-0000-0000-000000001003",
        goal_version=1,
        goal_title="2.000 m em 45 min",
        target_distance_m=2000,
        target_pace_seconds_per_100m=135,
        default_sessions_per_week=3,
        availability=tuple(
            AvailabilitySnapshot(
                date=week_start + timedelta(days=day),
                start_local_time="07:00",
                max_duration_minutes=45,
                pool_id="00000000-0000-0000-0000-000000001002",
            )
            for day in (0, 2, 5)
        ),
        recent_feedback=feedback,
        recent_weeks=(
            RecentWeekSnapshot(
                week_start=week_start - timedelta(days=7),
                planned_sessions=3,
                completed_sessions=3,
                completed_distance_m=4800,
                adherence=adherence,
            ),
        ),
    )


def test_same_context_ruleset_and_preferences_generate_identical_week() -> None:
    selected_context = context()
    selected_ruleset = ruleset()
    preferences = PlanningPreferences(focus="GOAL_PACE")

    first = generate_week(selected_context, selected_ruleset, preferences)
    second = generate_week(selected_context, selected_ruleset, preferences)

    assert first == second
    assert first.output_hash == second.output_hash
    assert first.phase == "build"
    assert first.target_volume_m <= 4800 * 1.08
    assert sum(item.distance_m for item in first.sessions) == first.target_volume_m
    assert all(item.distance_m % 20 == 0 for item in first.sessions)
    assert [item.order for item in first.decisions] == list(range(1, len(first.decisions) + 1))
    assert any(item.session_type == "technique" for item in first.sessions)
    assert first.output_hash == "e31028ff8982cef8ba488e67ef93bf7b6e21e0f857cabe21b840e31f8d0b039c"
    assert [(item.date, item.session_type, item.distance_m) for item in first.sessions] == [
        (date(2026, 8, 17), "technique", 1_700),
        (date(2026, 8, 19), "aerobic_endurance", 1_700),
        (date(2026, 8, 22), "threshold_css", 1_700),
    ]


def test_relevant_pain_forces_recovery_and_blocks_intensity() -> None:
    feedback = (
        FeedbackSnapshot(
            activity_id="00000000-0000-0000-0000-000000001020",
            activity_date=date(2026, 8, 15),
            rpe=9,
            technique_rating=2,
            pain_present=True,
            pain_intensity=6,
        ),
    )
    result = generate_week(
        context(feedback=feedback),
        ruleset(),
        PlanningPreferences(focus="GOAL_PACE"),
    )

    assert result.phase == "recovery"
    assert "PAIN_REVIEW_REQUIRED" in result.warnings
    assert all(not item.hard for item in result.sessions)
    assert all(item.session_type != "threshold_css" for item in result.sessions)
    assert result.target_volume_m <= 4800 * 0.8
    assert result.decisions[0].rule_id == "RULE-SAFETY-PAIN-001"


@pytest.mark.parametrize("adherence", [0.0, 0.5, 0.74])
def test_low_adherence_never_increases_volume(adherence: float) -> None:
    result = generate_week(
        context(adherence=adherence),
        ruleset(),
        PlanningPreferences(),
    )
    assert result.target_volume_m <= 4800
    assert result.phase == "recovery"


def test_duration_cap_reduces_output_without_partial_pool_lengths() -> None:
    selected_context = context().model_copy(
        update={
            "availability": tuple(
                item.model_copy(update={"max_duration_minutes": 20})
                for item in context().availability
            )
        }
    )
    result = generate_week(
        selected_context,
        ruleset(),
        PlanningPreferences(max_session_duration_minutes=20),
    )
    assert all(item.distance_m % 20 == 0 for item in result.sessions)
    assert all(item.max_duration_minutes == 20 for item in result.sessions)
    assert any(item.rule_id == "RULE-DURATION-001" for item in result.decisions)


def test_missed_sessions_are_not_rolled_forward_and_reschedule_stays_a_proposal() -> None:
    selected_context = context(adherence=0.5).model_copy(
        update={
            "recent_weeks": (
                RecentWeekSnapshot(
                    week_start=date(2026, 8, 10),
                    planned_sessions=3,
                    completed_sessions=1,
                    completed_distance_m=1_600,
                    adherence=0.5,
                ),
            ),
            "existing_sessions": (
                ExistingSessionSnapshot(
                    workout_id="00000000-0000-0000-0000-000000001030",
                    scheduled_date=date(2026, 8, 18),
                    distance_m=1_600,
                    purpose="ENDURANCE",
                ),
            ),
        }
    )
    result = generate_week(selected_context, ruleset(), PlanningPreferences())

    decisions = {item.rule_id: item for item in result.decisions}
    assert decisions["RULE-MISSED-SESSION-001"].after == {"rolled_forward_sessions": 0}
    assert decisions["RULE-RESCHEDULE-001"].before == {"session_dates": ["2026-08-18"]}
    assert result.target_volume_m <= 1_600


@settings(max_examples=40)
@given(
    available_days=st.sets(st.integers(min_value=0, max_value=6), min_size=1, max_size=7),
    duration_minutes=st.integers(min_value=20, max_value=120),
    adherence=st.floats(min_value=0, max_value=1, allow_nan=False, allow_infinity=False),
)
def test_generated_weeks_preserve_load_pool_and_recovery_invariants(
    available_days: set[int], duration_minutes: int, adherence: float
) -> None:
    selected_context = context(adherence=adherence).model_copy(
        update={
            "availability": tuple(
                AvailabilitySnapshot(
                    date=date(2026, 8, 17) + timedelta(days=day),
                    start_local_time="07:00",
                    max_duration_minutes=duration_minutes,
                    pool_id="00000000-0000-0000-0000-000000001002",
                )
                for day in sorted(available_days)
            )
        }
    )
    result = generate_week(
        selected_context,
        ruleset(),
        PlanningPreferences(session_count=min(7, len(available_days)), focus="GOAL_PACE"),
    )

    assert 1 <= len(result.sessions) <= 3
    assert result.target_volume_m == sum(item.distance_m for item in result.sessions)
    assert all(item.distance_m % 20 == 0 for item in result.sessions)
    assert all(item.max_duration_minutes <= duration_minutes for item in result.sessions)
    hard_dates = [item.date for item in result.sessions if item.hard]
    assert all((current - previous).days * 24 >= 36 for previous, current in pairwise(hard_dates))
    if adherence < 0.75:
        assert result.target_volume_m <= 4_800
        assert result.phase == "recovery"
