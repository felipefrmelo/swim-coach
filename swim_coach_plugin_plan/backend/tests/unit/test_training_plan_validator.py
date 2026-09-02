from __future__ import annotations

from datetime import date, time

import pytest

from swim_coach.application.services.training_cycles import TrainingCycleService
from swim_coach.application.services.training_plan_validator import (
    TrainingPlanValidationContext,
    TrainingPlanValidator,
)
from swim_coach.domain.athlete import AvailabilityRule, Pool
from swim_coach.domain.planning import (
    PlanDetailLevel,
    PlanSessionBinding,
    PlanSessionIntent,
    PlanSessionState,
    PlanWeek,
    PrescriptionSource,
    TrainingPlanDocument,
)
from swim_coach.domain.shared.errors import DomainError
from swim_coach.domain.shared.value_objects import EntityId, PoolLength, UserId
from swim_coach.domain.workouts import CanonicalWorkout

START = date(2026, 9, 7)


def workout(distance_m: int, *, pace: tuple[int, int] = (130, 140)) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "title": f"Coach workout {distance_m} m",
        "sport": "POOL_SWIMMING",
        "pool_length_m": 20,
        "purpose": "ENDURANCE",
        "tags": [],
        "nodes": [
            {
                "type": "step",
                "step_role": "WORK",
                "end_condition": {"type": "distance", "meters": distance_m},
                "target": {
                    "type": "pace_range",
                    "min_seconds_per_100m": pace[0],
                    "max_seconds_per_100m": pace[1],
                },
                "stroke": {"type": "freestyle"},
                "equipment": [],
            }
        ],
    }


def plan_definition(
    *,
    distance_m: int = 1_000,
    scheduled_date: date = date(2026, 9, 8),
    scheduled_start_time: time = time(6, 15),
    duration_minutes: int = 40,
    session_id: EntityId | None = None,
) -> TrainingPlanDocument:
    selected_session_id = session_id or EntityId.new()
    weeks = [
        PlanWeek(
            week_number=1,
            focus="Technique and aerobic continuity",
            detail_level=PlanDetailLevel.DETAILED,
            coach_rationale="Coach-authored first detailed week.",
            session_count=1,
            load_target="BUILD",
            sessions=(
                PlanSessionIntent(
                    session_intent_id=str(selected_session_id),
                    session_number=1,
                    purpose="ENDURANCE",
                    objective="Complete the prescribed distance with stable form.",
                    coach_rationale="Explicit coach decision.",
                    target_distance_m=distance_m,
                    planned_duration_minutes=duration_minutes,
                    intensity="MODERATE",
                    scheduled_date=scheduled_date,
                    scheduled_start_time=scheduled_start_time,
                    key_set=f"1 x {distance_m} m",
                    workout=workout(distance_m),
                ),
            ),
        ),
        *(
            PlanWeek(
                week_number=number,
                focus="Coach-defined strategic intent",
                detail_level=PlanDetailLevel.STRATEGIC,
                coach_rationale="Details will be authored explicitly in a future revision.",
            )
            for number in range(2, 5)
        ),
    ]
    return TrainingPlanDocument(
        schema_version="2.0",
        goal_id=str(EntityId.new()),
        title="2,000 m in 45 minutes",
        start_date=START,
        timezone="America/Sao_Paulo",
        prescription_source=PrescriptionSource.COACH_DEFINED,
        strategy_summary="Coach-authored strategy.",
        review_frequency="WEEKLY",
        duration_weeks=4,
        weeks=tuple(weeks),
    )


def validation_context() -> TrainingPlanValidationContext:
    user_id = UserId.new()
    pool = Pool(
        id=EntityId.new(),
        user_id=user_id,
        name="20 m pool",
        length=PoolLength(20),
        is_default=True,
    )
    availability = AvailabilityRule(
        id=EntityId.new(),
        user_id=user_id,
        day_of_week=1,
        start_local_time=time(6, 15),
        end_local_time=time(7),
        max_duration_minutes=45,
        pool_id=pool.id,
    )
    return TrainingPlanValidationContext(
        timezone="America/Sao_Paulo",
        pools=(pool,),
        availability=(availability,),
    )


def normalized(
    definition: TrainingPlanDocument, context: TrainingPlanValidationContext
) -> TrainingPlanDocument:
    pool_id = str(context.pools[0].id)
    weeks = tuple(
        week.model_copy(
            update={
                "sessions": tuple(
                    session.model_copy(update={"pool_id": pool_id}) for session in week.sessions
                )
            }
        )
        for week in definition.weeks
    )
    return definition.model_copy(update={"weeks": weeks})


def issue_codes(error: DomainError) -> set[str]:
    raw = error.details["issues"]
    assert isinstance(raw, list)
    return {str(item["code"]) for item in raw if isinstance(item, dict)}


def test_valid_coach_definition_is_accepted_without_mutation() -> None:
    context = validation_context()
    definition = normalized(plan_definition(), context)
    before = definition.model_dump(mode="json")

    TrainingPlanValidator().validate(definition, context)

    assert definition.model_dump(mode="json") == before


def test_detailed_session_without_explicit_pool_is_rejected_not_defaulted() -> None:
    context = validation_context()
    definition = plan_definition()

    with pytest.raises(DomainError) as captured:
        TrainingPlanValidator().validate(definition, context)

    assert "SESSION_POOL_REQUIRED" in issue_codes(captured.value)


def test_normalization_preserves_every_coach_authored_sport_decision() -> None:
    context = validation_context()
    definition = plan_definition()
    first_week = definition.weeks[0]
    tuesday = first_week.sessions[0]
    thursday = tuesday.model_copy(
        update={
            "session_intent_id": None,
            "session_number": 2,
            "purpose": "TECHNIQUE",
            "target_distance_m": 1_100,
            "scheduled_date": date(2026, 9, 10),
            "workout": CanonicalWorkout.model_validate(workout(1_100, pace=(135, 145))),
        }
    )
    supplied = definition.model_copy(
        update={
            "phases": (),
            "weeks": (
                first_week.model_copy(update={"session_count": 2, "sessions": (tuesday, thursday)}),
                *definition.weeks[1:],
            ),
        }
    )

    normalized_plan = TrainingCycleService._normalize_definition(
        supplied,
        timezone=context.timezone,
    )

    sessions = normalized_plan.weeks[0].sessions
    assert len(sessions) == 2
    assert [item.scheduled_date for item in sessions] == [
        date(2026, 9, 8),
        date(2026, 9, 10),
    ]
    assert [item.target_distance_m for item in sessions] == [1_000, 1_100]
    assert [item.purpose for item in sessions] == ["ENDURANCE", "TECHNIQUE"]
    assert [
        item.workout.model_dump(mode="json") if item.workout is not None else None
        for item in sessions
    ] == [
        CanonicalWorkout.model_validate(workout(1_000)).model_dump(mode="json"),
        CanonicalWorkout.model_validate(workout(1_100, pace=(135, 145))).model_dump(mode="json"),
    ]
    assert normalized_plan.phases == ()
    assert [week.detail_level for week in normalized_plan.weeks] == [
        PlanDetailLevel.DETAILED,
        PlanDetailLevel.STRATEGIC,
        PlanDetailLevel.STRATEGIC,
        PlanDetailLevel.STRATEGIC,
    ]


def test_fifty_metres_is_rejected_for_twenty_metre_pool_with_structured_issue() -> None:
    context = validation_context()
    definition = normalized(plan_definition(distance_m=50), context)

    with pytest.raises(DomainError) as captured:
        TrainingPlanValidator().validate(definition, context)

    assert "DISTANCE_NOT_POOL_ALIGNED" in issue_codes(captured.value)
    issues = captured.value.details["issues"]
    assert isinstance(issues, list)
    mismatch = next(item for item in issues if item["code"] == "DISTANCE_NOT_POOL_ALIGNED")
    assert mismatch["value"] == 50
    assert mismatch["pool_length_m"] == 20


def test_forty_metres_is_accepted_for_twenty_metre_pool() -> None:
    context = validation_context()
    definition = normalized(plan_definition(distance_m=40, duration_minutes=5), context)

    TrainingPlanValidator().validate(definition, context)


def test_session_outside_availability_is_rejected() -> None:
    context = validation_context()
    definition = normalized(
        plan_definition(scheduled_start_time=time(7, 15)),
        context,
    )

    with pytest.raises(DomainError) as captured:
        TrainingPlanValidator().validate(definition, context)

    assert "SESSION_OUTSIDE_AVAILABILITY" in issue_codes(captured.value)


def test_session_duration_above_availability_is_rejected() -> None:
    context = validation_context()
    definition = normalized(plan_definition(duration_minutes=50), context)

    with pytest.raises(DomainError) as captured:
        TrainingPlanValidator().validate(definition, context)

    assert "SESSION_DURATION_EXCEEDS_AVAILABILITY" in issue_codes(captured.value)


def test_target_distance_must_equal_workout_without_rounding() -> None:
    context = validation_context()
    definition = normalized(plan_definition(), context)
    first_week = definition.weeks[0]
    session = first_week.sessions[0].model_copy(update={"target_distance_m": 960})
    candidate = definition.model_copy(
        update={
            "weeks": (
                first_week.model_copy(update={"sessions": (session,)}),
                *definition.weeks[1:],
            )
        }
    )

    with pytest.raises(DomainError) as captured:
        TrainingPlanValidator().validate(candidate, context)

    assert "WORKOUT_DISTANCE_MISMATCH" in issue_codes(captured.value)


def test_locked_session_cannot_be_changed_or_removed() -> None:
    context = validation_context()
    session_id = EntityId.new()
    before = normalized(plan_definition(session_id=session_id), context)
    first_week = before.weeks[0]
    changed_session = first_week.sessions[0].model_copy(update={"target_distance_m": 960})
    after = before.model_copy(
        update={
            "weeks": (
                first_week.model_copy(update={"sessions": (changed_session,)}),
                *before.weeks[1:],
            )
        }
    )
    binding = PlanSessionBinding(
        id=EntityId.new(),
        user_id=UserId.new(),
        plan_id=EntityId.new(),
        session_intent_id=session_id,
        week_number=1,
        state=PlanSessionState.COMPLETED,
    )

    with pytest.raises(DomainError) as captured:
        TrainingPlanValidator().validate(
            after,
            context,
            previous=before,
            bindings=(binding,),
        )

    assert "PLAN_SESSION_LOCKED" in issue_codes(captured.value)


def test_activity_linked_session_is_immutable_even_if_binding_state_is_materialized() -> None:
    context = validation_context()
    session_id = EntityId.new()
    before = normalized(plan_definition(session_id=session_id), context)
    first_week = before.weeks[0]
    changed_session = first_week.sessions[0].model_copy(
        update={"scheduled_start_time": time(6, 30)}
    )
    after = before.model_copy(
        update={
            "weeks": (
                first_week.model_copy(update={"sessions": (changed_session,)}),
                *before.weeks[1:],
            )
        }
    )

    with pytest.raises(DomainError) as captured:
        TrainingPlanValidator().validate(
            after,
            context,
            previous=before,
            immutable_session_ids=frozenset({str(session_id)}),
        )

    assert "PLAN_SESSION_LOCKED" in issue_codes(captured.value)


def test_materialization_only_details_one_future_outline_or_strategic_week() -> None:
    context = validation_context()
    before = normalized(plan_definition(), context)
    source_session = before.weeks[0].sessions[0]
    detailed_session = source_session.model_copy(
        update={
            "session_intent_id": str(EntityId.new()),
            "scheduled_date": date(2026, 9, 15),
        }
    )
    detailed_week = before.weeks[1].model_copy(
        update={
            "detail_level": PlanDetailLevel.DETAILED,
            "session_count": 1,
            "sessions": (detailed_session,),
        }
    )
    after = before.model_copy(update={"weeks": (before.weeks[0], detailed_week, *before.weeks[2:])})

    TrainingPlanValidator().validate(
        after,
        context,
        previous=before,
        revision_kind="MATERIALIZATION",
    )


def test_materialization_cannot_hide_strategy_or_phase_changes() -> None:
    context = validation_context()
    before = normalized(plan_definition(), context)
    source_session = before.weeks[0].sessions[0]
    detailed_week = before.weeks[1].model_copy(
        update={
            "detail_level": PlanDetailLevel.DETAILED,
            "session_count": 1,
            "sessions": (
                source_session.model_copy(
                    update={
                        "session_intent_id": str(EntityId.new()),
                        "scheduled_date": date(2026, 9, 15),
                    }
                ),
            ),
        }
    )
    after = before.model_copy(
        update={
            "strategy_summary": "A hidden strategy change is not materialization.",
            "weeks": (before.weeks[0], detailed_week, *before.weeks[2:]),
        }
    )

    with pytest.raises(DomainError) as captured:
        TrainingPlanValidator().validate(
            after,
            context,
            previous=before,
            revision_kind="MATERIALIZATION",
        )

    assert "MATERIALIZATION_SCOPE_INVALID" in issue_codes(captured.value)
