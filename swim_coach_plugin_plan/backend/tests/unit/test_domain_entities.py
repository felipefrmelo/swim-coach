from datetime import date, time
from decimal import Decimal

import pytest

from swim_coach.domain.athlete import AthleteProfile, AvailabilityRule, Pool
from swim_coach.domain.goals import TrainingGoal
from swim_coach.domain.shared import (
    Distance,
    DomainValidationError,
    Duration,
    EntityId,
    PoolLength,
    UserId,
)


def test_initial_goal_is_two_k_in_45_minutes_at_135_seconds_per_100m() -> None:
    goal = TrainingGoal.initial_two_k(UserId.new())

    assert goal.target_distance == Distance(2_000)
    assert goal.target_duration == Duration(Decimal(2_700))
    assert goal.target_pace.seconds_per_100m == Decimal(135)


def test_athlete_profile_and_pool_keep_initial_invariants() -> None:
    user_id = UserId.new()
    pool = Pool(EntityId.new(), user_id, "Principal", PoolLength(20), is_default=True)
    profile = AthleteProfile(user_id=user_id, default_pool_id=pool.id)

    assert profile.default_pool_id == pool.id
    assert profile.default_sessions_per_week == 3


def test_availability_rejects_inverted_time_window() -> None:
    with pytest.raises(DomainValidationError):
        AvailabilityRule(
            id=EntityId.new(),
            user_id=UserId.new(),
            day_of_week=1,
            start_local_time=time(20),
            end_local_time=time(19),
            max_duration_minutes=60,
            valid_from=date(2026, 8, 11),
        )
