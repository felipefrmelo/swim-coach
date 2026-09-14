from copy import deepcopy
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from swim_coach.application.services.activity_data import ActivityDataService
from swim_coach.application.services.privacy import _jsonable
from swim_coach.application.services.training_cycles import TrainingCycleService
from swim_coach.application.services.weekly_checkpoint import adaptation_metrics, weekly_checkpoint
from swim_coach.domain.activities import SessionFeedback
from swim_coach.domain.activities.checkin import SwimCheckIn, execution_evidence
from swim_coach.domain.planning import PlanDetailLevel, PlanSessionState
from swim_coach.domain.shared import CorrelationId, EntityId, UserId
from swim_coach.domain.shared.errors import ResourceNotFoundError
from swim_coach.interfaces.rest.activities_v2 import FeedbackRequestV2, put_feedback_v2


async def test_rest_idempotency_distinguishes_preserving_and_clearing_checkin() -> None:
    service = SimpleNamespace(record_feedback=AsyncMock(return_value=None))
    activity_id = EntityId.new().value
    authenticated = SimpleNamespace(user=SimpleNamespace(id=UserId.new()))
    for payload in (FeedbackRequestV2(), FeedbackRequestV2(check_in=None)):
        await put_feedback_v2(
            activity_id,
            payload,
            "same-key",
            authenticated,
            SimpleNamespace(activity_data=service),
            CorrelationId.new(),
        )
    preserve, clear = service.record_feedback.call_args_list
    assert preserve.kwargs["request_hash"] != clear.kwargs["request_hash"]
    assert preserve.kwargs["preserve_existing_check_in"] is True
    assert clear.kwargs["preserve_existing_check_in"] is False
    assert preserve.kwargs["check_in_only"] is False
    assert clear.kwargs["check_in_only"] is True


@pytest.mark.parametrize("completed", [None, False, True])
def test_watch_error_never_implies_completion_or_repairs_performance(completed) -> None:
    report = SwimCheckIn(completed_as_planned=completed, watch_data_accurate=False)
    evidence = execution_evidence(report)
    assert (
        evidence["completion"]
        == {None: "UNCONFIRMED", False: "CONFIRMED_PARTIAL", True: "CONFIRMED_COMPLETE"}[completed]
    )
    assert evidence["performance_blocked"] is True
    assert "distance_m" not in evidence
    assert "pace" not in evidence


@pytest.mark.parametrize(
    "invalid",
    [
        {"completed_as_planned": "yes"},
        {"watch_data_accurate": 1},
        {"main_difficulty": "x" * 501},
        {"corrected_distance": 1040},
    ],
)
def test_check_in_rejects_implicit_units_and_invalid_answers(invalid) -> None:
    with pytest.raises(ValidationError):
        SwimCheckIn.model_validate(invalid)


def test_disputed_metrics_are_excluded_without_mutating_raw_analysis() -> None:
    metrics = {
        "paces": {"swim_s_per_100m": "150"},
        "sets": [{"quality": "HIGH"}],
        "session_evaluation": {"effective": {"rpe": "4"}},
        "srpe": {"load": 150},
    }
    before = deepcopy(metrics)
    usable = adaptation_metrics(metrics, blocked=True)
    assert metrics == before
    assert "paces" not in usable
    assert "srpe" not in usable
    assert usable["sets"] == []
    assert usable["session_evaluation"] == metrics["session_evaluation"]
    assert adaptation_metrics(metrics, blocked=False) == metrics


def test_checkpoint_separates_attendance_completion_response_and_reliability() -> None:
    activities = [
        {
            "activity_id": "a",
            "execution_evidence": execution_evidence(
                SwimCheckIn(
                    completed_as_planned=True,
                    watch_data_accurate=False,
                    main_difficulty="Respiração",
                )
            ),
            "data_quality": {"level": "LOW"},
            "feedback": {"pain_present": False},
            "metrics": {"session_evaluation": {"effective": {"rpe": "4"}}},
        },
        {
            "activity_id": "b",
            "execution_evidence": execution_evidence(None),
            "data_quality": {"level": "LOW"},
            "feedback": None,
            "metrics": {},
        },
    ]
    brief = weekly_checkpoint(activities)
    assert brief["execution"]["recorded_sessions"] == 2
    assert brief["execution"]["confirmed_complete_sessions"] == 1
    assert brief["execution"]["unconfirmed_sessions"] == 1
    assert brief["measurement"]["excluded_performance_activity_ids"] == ["a"]
    assert {q["activity_id"] for q in brief["missing_context"]} == {"b"}
    assert brief["athlete_response"][0]["main_difficulty"] == "Respiração"
    assert brief["decision"] is None


def test_athlete_confirmation_does_not_upgrade_measurement_quality() -> None:
    evidence = execution_evidence(SwimCheckIn(watch_data_accurate=True, all_freestyle=True))
    assert evidence["performance_blocked"] is False
    assert evidence["completion"] == "UNCONFIRMED"
    assert "data-quality" in evidence["guidance"]


def test_checkin_exports_as_structured_data() -> None:
    feedback = SessionFeedback(
        id=EntityId.new(),
        user_id=UserId.new(),
        activity_id=EntityId.new(),
        rpe=None,
        check_in=SwimCheckIn(completed_as_planned=True),
    )
    assert _jsonable(feedback)["check_in"]["completed_as_planned"] is True


def make_service(existing=None, *, activity_exists=True):
    user_id = existing.user_id if existing else UserId.new()
    activity_id = existing.activity_id if existing else EntityId.new()
    activity = SimpleNamespace(id=activity_id, provider="garmin", external_activity_id="synthetic")
    data = SimpleNamespace(
        get_feedback=AsyncMock(return_value=existing),
        get_current_normalization=AsyncMock(return_value=None),
        upsert_feedback=AsyncMock(),
        delete_feedback=AsyncMock(),
    )
    uow = SimpleNamespace(
        activities=SimpleNamespace(
            get=AsyncMock(return_value=activity if activity_exists else None)
        ),
        activity_data=data,
        audit=SimpleNamespace(add=AsyncMock()),
        commit=AsyncMock(),
    )
    context = AsyncMock()
    context.__aenter__.return_value = uow
    factory = MagicMock(return_value=context)
    service = ActivityDataService(factory, None, MagicMock(), MagicMock())
    kwargs = dict(
        rpe=None,
        technique_rating=None,
        fatigue_rating=None,
        enjoyment_rating=None,
        pain_present=False,
        pain_location=None,
        pain_intensity=None,
        comment=None,
        expected_version=None,
        actor_id="fixture",
        correlation_id=CorrelationId.new(),
    )
    return service, user_id, activity_id, data, kwargs


async def test_checkin_can_be_saved_without_garmin_rpe() -> None:
    service, user_id, activity_id, data, kwargs = make_service()
    stored = await service.record_feedback(
        user_id,
        activity_id,
        **kwargs,
        check_in=SwimCheckIn(completed_as_planned=True, watch_data_accurate=False),
        check_in_only=True,
    )
    assert stored.rpe is None
    assert stored.check_in.completed_as_planned is True
    data.upsert_feedback.assert_awaited_once_with(stored, expected_version=None)


async def test_checkin_only_merges_answers_and_preserves_pain_rpe_and_notes() -> None:
    existing = SessionFeedback(
        id=EntityId.new(),
        user_id=UserId.new(),
        activity_id=EntityId.new(),
        rpe=6,
        feeling_score=50,
        technique_rating=3,
        pain_present=True,
        pain_location="ombro",
        pain_intensity=3,
        comment="fixture",
        check_in=SwimCheckIn(completed_as_planned=True, watch_data_accurate=False),
    )
    service, user_id, activity_id, data, kwargs = make_service(existing)
    stored = await service.record_feedback(
        user_id,
        activity_id,
        **kwargs,
        check_in=SwimCheckIn(main_difficulty="Respiração"),
        check_in_only=True,
    )
    assert stored.rpe == 6 and stored.feeling_score == 50 and stored.technique_rating == 3
    assert stored.pain_present and stored.pain_intensity == 3 and stored.comment == "fixture"
    assert stored.check_in.completed_as_planned is True
    assert stored.check_in.watch_data_accurate is False
    assert stored.check_in.main_difficulty == "Respiração"
    assert stored.version == 2
    data.upsert_feedback.assert_awaited_once_with(stored, expected_version=1)


async def test_legacy_feedback_cannot_erase_checkin_it_does_not_know_about() -> None:
    existing = SessionFeedback(
        id=EntityId.new(),
        user_id=UserId.new(),
        activity_id=EntityId.new(),
        rpe=6,
        check_in=SwimCheckIn(watch_data_accurate=False),
    )
    service, user_id, activity_id, _, kwargs = make_service(existing)
    stored = await service.record_feedback(user_id, activity_id, **{**kwargs, "rpe": 5})
    assert stored.check_in.watch_data_accurate is False


async def test_explicit_full_clear_removes_checkin_too() -> None:
    existing = SessionFeedback(
        id=EntityId.new(),
        user_id=UserId.new(),
        activity_id=EntityId.new(),
        rpe=None,
        check_in=SwimCheckIn(watch_data_accurate=False),
    )
    service, user_id, activity_id, data, kwargs = make_service(existing)
    stored = await service.record_feedback(
        user_id, activity_id, **kwargs, check_in=None, preserve_existing_check_in=False
    )
    assert stored is None
    data.delete_feedback.assert_awaited_once()


async def test_checkin_cannot_bypass_activity_ownership() -> None:
    service, user_id, activity_id, data, kwargs = make_service(activity_exists=False)
    with pytest.raises(ResourceNotFoundError):
        await service.record_feedback(
            user_id, activity_id, **kwargs, check_in=SwimCheckIn(completed_as_planned=True)
        )
    data.upsert_feedback.assert_not_awaited()


async def test_review_week_uses_latest_checkin_and_excludes_disputed_performance() -> None:
    user_id, activity_id, plan_id, intent_id, workout_id = (
        UserId.new(),
        EntityId.new(),
        EntityId.new(),
        EntityId.new(),
        EntityId.new(),
    )
    report = SessionFeedback(
        id=EntityId.new(),
        user_id=user_id,
        activity_id=activity_id,
        rpe=4,
        pain_present=True,
        pain_intensity=2,
        pain_location="ombro",
        check_in=SwimCheckIn(completed_as_planned=True, watch_data_accurate=False),
    )
    week = SimpleNamespace(
        detail_level=PlanDetailLevel.DETAILED,
        session_count=1,
        sessions=[SimpleNamespace(session_intent_id=str(intent_id), target_distance_m=1040)],
    )
    plan = SimpleNamespace(
        id=plan_id, current_revision=1, duration_weeks=1, start_date=date(2000, 1, 3)
    )
    detail = SimpleNamespace(
        plan=plan,
        revision=SimpleNamespace(document=SimpleNamespace(weeks=[week])),
        notes=[],
        bindings=[
            SimpleNamespace(
                week_number=1,
                session_intent_id=intent_id,
                workout_id=workout_id,
                state=PlanSessionState.MATERIALIZED,
            )
        ],
    )
    raw_metrics = {
        "data_quality": {"level": "HIGH"},
        "sets": [{"quality": "HIGH"}],
        "paces": {"swim_s_per_100m": "169"},
        "srpe": {"load": 140},
    }
    uow = SimpleNamespace(
        users=SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(timezone="UTC"))),
        activities=SimpleNamespace(
            get=AsyncMock(
                return_value=SimpleNamespace(
                    id=activity_id,
                    provider="garmin",
                    external_activity_id="fixture",
                    distance=SimpleNamespace(meters=920),
                )
            )
        ),
        activity_data=SimpleNamespace(
            get_match_by_workout=AsyncMock(return_value=SimpleNamespace(activity_id=activity_id)),
            get_analysis=AsyncMock(return_value=SimpleNamespace(metrics=raw_metrics)),
            get_feedback=AsyncMock(return_value=report),
            get_current_normalization=AsyncMock(return_value=None),
        ),
        plan_reviews=SimpleNamespace(add=AsyncMock(side_effect=lambda review: review)),
        audit=SimpleNamespace(add=AsyncMock()),
        commit=AsyncMock(),
    )
    context = AsyncMock()
    context.__aenter__.return_value = uow
    service = TrainingCycleService(
        uow_factory=MagicMock(return_value=context), workouts=MagicMock()
    )
    service.get_plan = AsyncMock(return_value=detail)
    first = await service.review_week(
        user_id,
        actor_id="fixture",
        plan_id=plan_id,
        week_number=1,
        correlation_id=CorrelationId.new(),
    )
    evidence = first.evidence_snapshot
    assert first.confidence_cap.value == "LOW"
    assert first.eligible is True
    assert evidence["executed_distance_m"] == 920
    assert evidence["distance_adherence_ratio"] is None
    assert evidence["comparable_evidence_count"] == 0
    assert evidence["coach_checkpoint"]["execution"]["confirmed_complete_sessions"] == 1
    assert evidence["activities"][0]["metrics"]["paces"] is None
    assert evidence["activities"][0]["metrics"]["srpe"] is None
    assert evidence["activities"][0]["metrics"]["session_evaluation"]["effective"]["rpe"] == "4"
    assert len(evidence["pain_signals"]) == 1
    assert raw_metrics["sets"] == [{"quality": "HIGH"}]
    # A new feedback snapshot is not allowed to mutate a previously stored review.
    report.check_in = SwimCheckIn(completed_as_planned=False, watch_data_accurate=False)
    second = await service.review_week(
        user_id,
        actor_id="fixture",
        plan_id=plan_id,
        week_number=1,
        correlation_id=CorrelationId.new(),
    )
    assert second.evidence_hash != first.evidence_hash
    assert (
        first.evidence_snapshot["coach_checkpoint"]["execution"]["confirmed_complete_sessions"] == 1
    )
    assert (
        second.evidence_snapshot["coach_checkpoint"]["execution"]["confirmed_partial_sessions"] == 1
    )
