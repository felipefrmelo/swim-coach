from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import cast

import pytest

from swim_coach.application.ports.repositories import UnitOfWorkFactory
from swim_coach.application.services.activity_data import ActivityDataService
from swim_coach.application.services.context import ContextService
from swim_coach.application.services.identity import IdentityService
from swim_coach.application.services.mcp_read import McpPrincipal, McpReadService
from swim_coach.application.services.workouts import WorkoutService
from swim_coach.domain.goals import GoalStatus, TrainingGoal
from swim_coach.domain.shared import Distance, Duration, EntityId, UserId


class _GoalProgressUnitOfWork:
    def __init__(self, goal: TrainingGoal, samples: list[tuple[object, object]]) -> None:
        self.goals = SimpleNamespace(list=self._list_goals, get=self._get_goal)
        self.activities = SimpleNamespace(list_recent=self._list_recent)
        self.activity_data = SimpleNamespace(list_analyses=self._list_analyses)
        self._goal = goal
        self._activities = [activity for activity, _analysis in samples]
        self._analyses = [analysis for _activity, analysis in samples]

    async def __aenter__(self) -> _GoalProgressUnitOfWork:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def _list_goals(self, user_id: UserId) -> list[TrainingGoal]:
        assert user_id == self._goal.user_id
        return [self._goal]

    async def _get_goal(self, user_id: UserId, goal_id: EntityId) -> TrainingGoal | None:
        assert user_id == self._goal.user_id
        return self._goal if goal_id == self._goal.id else None

    async def _list_recent(self, user_id: UserId, **_: object) -> list[object]:
        assert user_id == self._goal.user_id
        return self._activities

    async def _list_analyses(self, user_id: UserId, activity_ids: list[EntityId]) -> list[object]:
        assert user_id == self._goal.user_id
        assert activity_ids == [activity.id for activity in self._activities]
        return self._analyses


class _GoalProgressUnitOfWorkFactory:
    def __init__(self, uow: _GoalProgressUnitOfWork) -> None:
        self._uow = uow

    def __call__(self) -> _GoalProgressUnitOfWork:
        return self._uow


def _sample(
    *,
    user_id: UserId,
    distance_m: int,
    pace_s_per_100m: Decimal,
    quality: str,
    day_offset: int,
) -> tuple[object, object]:
    activity_id = EntityId.new()
    activity = SimpleNamespace(
        id=activity_id,
        user_id=user_id,
        start_time_utc=datetime(2026, 9, 1, tzinfo=UTC) - timedelta(days=day_offset),
    )
    metrics = {
        "goal_readiness": {
            "longest_evidence_distance_m": distance_m,
            "evidence_pace_s_per_100m": str(pace_s_per_100m),
            "evidence_pace_basis": "continuous_window",
            "confidence": quality,
        },
        "speed_endurance": {
            "speed": {
                "longest_distance_m": distance_m,
                "best_pace_s_per_100m": str(pace_s_per_100m),
                "quality": quality,
            }
        },
        "sets": [],
    }
    analysis = SimpleNamespace(activity_id=activity_id, metrics=metrics)
    return activity, analysis


def _service(goal: TrainingGoal, samples: list[tuple[object, object]]) -> McpReadService:
    uow = _GoalProgressUnitOfWork(goal, samples)
    return McpReadService(
        uow_factory=cast(UnitOfWorkFactory, _GoalProgressUnitOfWorkFactory(uow)),
        identity=cast(IdentityService, object()),
        context=cast(ContextService, object()),
        workouts=cast(WorkoutService, object()),
        activity_data=cast(ActivityDataService, object()),
    )


async def _progress(goal: TrainingGoal, samples: list[tuple[object, object]]) -> object:
    service = _service(goal, samples)
    principal = McpPrincipal(goal.user_id, "fixture", frozenset({"coach"}))
    return await service.get_goal_progress(principal, "request", goal_id=None)


@pytest.mark.asyncio
async def test_low_quality_selected_evidence_cannot_mark_goal_achieved() -> None:
    user_id = UserId.new()
    goal = TrainingGoal.initial_two_k(user_id)
    samples = [
        _sample(
            user_id=user_id,
            distance_m=2_000,
            pace_s_per_100m=Decimal(130),
            quality="LOW",
            day_offset=0,
        ),
        _sample(
            user_id=user_id,
            distance_m=800,
            pace_s_per_100m=Decimal(145),
            quality="HIGH",
            day_offset=7,
        ),
    ]

    result = await _progress(goal, samples)
    readiness = result.data["dimensions"]["goal_readiness"]
    confidence = result.data["dimensions"]["confidence"]

    assert result.status == "PARTIAL"
    assert result.data["selected_goal_evidence_quality"] == "LOW"
    assert readiness["status"] == "INSUFFICIENT_EVIDENCE_QUALITY"
    assert readiness["selected_evidence_quality"] == "LOW"
    assert confidence["level"] == "LOW"
    assert confidence["score"] == 0.49
    assert confidence["reasons"] == ["SELECTED_GOAL_EVIDENCE_LOW_QUALITY"]
    assert "ACHIEVED" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_short_indicators_are_excluded_from_goal_specific_sample_and_confidence() -> None:
    user_id = UserId.new()
    goal = TrainingGoal.initial_two_k(user_id)
    samples = [
        _sample(
            user_id=user_id,
            distance_m=40,
            pace_s_per_100m=Decimal(120),
            quality="HIGH",
            day_offset=0,
        ),
        _sample(
            user_id=user_id,
            distance_m=200,
            pace_s_per_100m=Decimal(128),
            quality="HIGH",
            day_offset=7,
        ),
    ]

    result = await _progress(goal, samples)
    confidence = result.data["dimensions"]["confidence"]
    readiness = result.data["dimensions"]["goal_readiness"]

    assert result.status == "PARTIAL"
    assert result.data["sample_size"] == 2
    assert result.data["goal_evidence_sample_size"] == 0
    assert result.data["short_distance_indicator_sample_size"] == 2
    assert result.data["longest_goal_evidence_distance_m"] == 0
    assert result.data["goal_evidence_pace_s_per_100m"] is None
    assert result.data["sample_quality"] == "LOW"
    assert confidence == {
        "sample_size": 0,
        "score": 0,
        "level": "LOW",
        "reasons": ["NO_GOAL_SPECIFIC_EVIDENCE"],
    }
    assert readiness["status"] == "INSUFFICIENT_GOAL_SPECIFIC_EVIDENCE"
    assert result.data["dimensions"]["speed"]["analyzed_sessions"] == 2
    assert result.data["dimensions"]["speed"]["longest_evidence_distance_m"] == 200
    assert "only in the separate speed/endurance dimensions" in result.human_summary
    assert {warning.code for warning in result.warnings} == {"GOAL_EVIDENCE_LIMITED"}


@pytest.mark.asyncio
async def test_goal_specific_minimum_uses_goal_distance_when_goal_is_under_400m() -> None:
    user_id = UserId.new()
    goal = TrainingGoal(
        id=EntityId.new(),
        user_id=user_id,
        goal_type="distance_time",
        title="200 m em 4:30",
        status=GoalStatus.ACTIVE,
        priority=1,
        target_distance=Distance(200),
        target_duration=Duration(Decimal(270)),
    )
    samples = [
        _sample(
            user_id=user_id,
            distance_m=200,
            pace_s_per_100m=Decimal(135),
            quality="HIGH",
            day_offset=0,
        )
    ]

    result = await _progress(goal, samples)

    assert result.status == "OK"
    assert result.data["goal_specific_minimum_distance_m"] == 200
    assert result.data["goal_evidence_sample_size"] == 1
    assert result.data["dimensions"]["goal_readiness"]["status"] == "ACHIEVED"
