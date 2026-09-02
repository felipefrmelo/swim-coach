"""Legacy ruleset planner retained only to read and test historical P10 records.

This module is intentionally absent from runtime composition and MCP registration. New
training prescriptions must use ``TrainingCycleService`` with a coach-authored definition.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Literal, cast, overload
from zoneinfo import ZoneInfo

from swim_coach.application.ports.repositories import UnitOfWorkFactory
from swim_coach.domain.actions import ActionProposal
from swim_coach.domain.activities import resolve_session_evaluation
from swim_coach.domain.goals import GoalStatus
from swim_coach.domain.operations import AuditEvent, OutboxEvent
from swim_coach.domain.planning import (
    AvailabilitySnapshot,
    ConstraintSnapshot,
    ExistingSessionSnapshot,
    FeedbackSnapshot,
    PlanningContext,
    PlanningPreferences,
    PlanningRules,
    PlanningRun,
    PlanningRunStatus,
    RecentWeekSnapshot,
    TrainingDecisionRecord,
    TrainingRuleSet,
    canonical_json_hash,
)
from swim_coach.domain.planning.entities import generate_week
from swim_coach.domain.shared.errors import DomainError, ResourceNotFoundError
from swim_coach.domain.shared.types import JsonObject
from swim_coach.domain.shared.value_objects import CorrelationId, EntityId, UserId


class PlanningService:
    """Deprecated ruleset generator; never compose this service in an application runtime."""

    ACTION_TYPE = "planning.week.v1"
    RULESET_NAME = "swim-coach-conservative-week"
    LEGACY_RULESET_VERSION = "1.0.0"
    LEGACY_RULESET_EFFECTIVE_FROM = date(2026, 8, 12)
    RULESET_VERSION = "1.1.0"
    RULESET_EFFECTIVE_FROM = date(2026, 9, 1)

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    @overload
    async def propose_week(
        self,
        user_id: UserId,
        *,
        actor_id: str,
        week_start: date,
        preferences: PlanningPreferences,
        user_notes_present: bool,
        correlation_id: CorrelationId,
        create_proposal: Literal[True] = True,
    ) -> tuple[PlanningRun, ActionProposal, bool]: ...

    @overload
    async def propose_week(
        self,
        user_id: UserId,
        *,
        actor_id: str,
        week_start: date,
        preferences: PlanningPreferences,
        user_notes_present: bool,
        correlation_id: CorrelationId,
        create_proposal: Literal[False],
    ) -> tuple[PlanningRun, None, bool]: ...

    async def propose_week(
        self,
        user_id: UserId,
        *,
        actor_id: str,
        week_start: date,
        preferences: PlanningPreferences,
        user_notes_present: bool,
        correlation_id: CorrelationId,
        create_proposal: bool = True,
    ) -> tuple[PlanningRun, ActionProposal | None, bool]:
        if week_start.weekday() != 0:
            raise DomainError("VALIDATION_FAILED", "week_start must be a Monday.")
        context = await self._snapshot(user_id, week_start)
        now = datetime.now(UTC).replace(microsecond=0)
        async with self._uow_factory() as uow:
            ruleset = await uow.training_rule_sets.get_active(week_start)
            if ruleset is None or (
                week_start >= self.RULESET_EFFECTIVE_FROM
                and ruleset.version != self.RULESET_VERSION
            ):
                legacy_week = week_start < self.RULESET_EFFECTIVE_FROM
                rules = PlanningRules() if legacy_week else PlanningRules(low_feeling_threshold=25)
                ruleset = TrainingRuleSet(
                    id=EntityId.new(),
                    name=self.RULESET_NAME,
                    version=(self.LEGACY_RULESET_VERSION if legacy_week else self.RULESET_VERSION),
                    rules=rules,
                    content_hash=canonical_json_hash(
                        rules.model_dump(mode="json", exclude_none=True)
                    ),
                    effective_from=(
                        self.LEGACY_RULESET_EFFECTIVE_FROM
                        if legacy_week
                        else self.RULESET_EFFECTIVE_FROM
                    ),
                    created_at=now,
                )
                existing_ruleset = await uow.training_rule_sets.get_by_hash(ruleset.content_hash)
                if existing_ruleset is None:
                    await uow.training_rule_sets.add(ruleset)
                    await uow.flush()
                else:
                    ruleset = existing_ruleset

            input_snapshot = cast(
                JsonObject,
                {
                    "context": context.model_dump(mode="json"),
                    "preferences": preferences.model_dump(mode="json"),
                    "user_notes_present": user_notes_present,
                    "delivery": "proposal" if create_proposal else "direct",
                },
            )
            input_hash = canonical_json_hash(input_snapshot)
            replay = await uow.planning_runs.get_by_input(user_id, ruleset.id, input_hash)
            if replay is not None:
                if not create_proposal:
                    return replay, None, True
                if replay.output_proposal_id is None:
                    raise DomainError("INTERNAL_ERROR", "Planning replay is missing its proposal.")
                replay_proposal = await uow.action_proposals.get(user_id, replay.output_proposal_id)
                if replay_proposal is None:
                    raise DomainError("INTERNAL_ERROR", "Planning replay proposal is missing.")
                return replay, replay_proposal, True

            generated = generate_week(context, ruleset, preferences)
            run_id = EntityId.new()
            output_plan = cast(JsonObject, generated.model_dump(mode="json"))
            proposal = (
                ActionProposal.ready_for_review(
                    id=EntityId.new(),
                    user_id=user_id,
                    action_type=self.ACTION_TYPE,
                    target_type="training_goal",
                    target_id=EntityId.parse(context.goal_id),
                    target_revision_id=None,
                    payload=cast(
                        JsonObject,
                        {
                            "planning_run_id": str(run_id),
                            "week": output_plan,
                            "input_hash": input_hash,
                            "ruleset_version": ruleset.version,
                            "ruleset_hash": ruleset.content_hash,
                        },
                    ),
                    impact=cast(
                        JsonObject,
                        {
                            "before": {
                                "session_count": len(context.existing_sessions),
                                "distance_m": sum(
                                    item.distance_m for item in context.existing_sessions
                                ),
                            },
                            "after": {
                                "session_count": len(generated.sessions),
                                "distance_m": generated.target_volume_m,
                                "session_dates": [
                                    item.date.isoformat() for item in generated.sessions
                                ],
                            },
                            "decision_count": len(generated.decisions),
                            "warnings": list(generated.warnings),
                            "external_effects": [],
                            "approval_effect": "REVIEW_ONLY_NO_STATE_CHANGE",
                        },
                    ),
                    expires_at=now + timedelta(hours=24),
                    created_at=now,
                )
                if create_proposal
                else None
            )
            run = PlanningRun(
                id=run_id,
                user_id=user_id,
                goal_id=EntityId.parse(context.goal_id),
                rule_set_id=ruleset.id,
                week_start=week_start,
                input_snapshot=input_snapshot,
                input_hash=input_hash,
                output_plan=output_plan,
                output_proposal_id=proposal.id if proposal is not None else None,
                status=PlanningRunStatus.COMPLETED,
                warnings=generated.warnings,
                created_at=now,
                completed_at=now,
            )
            if proposal is not None:
                await uow.action_proposals.add(proposal)
                await uow.flush()
            await uow.planning_runs.add(run)
            await uow.flush()
            for decision in generated.decisions:
                await uow.training_decisions.add(
                    TrainingDecisionRecord(
                        id=EntityId.new(),
                        user_id=user_id,
                        planning_run_id=run.id,
                        order_index=decision.order,
                        decision_type=decision.decision_type,
                        rule_id=decision.rule_id,
                        effective_date=week_start,
                        evidence_refs=decision.evidence_refs,
                        before=decision.before,
                        after=decision.after,
                        rationale=decision.rationale,
                        actor_type="mcp",
                        actor_id=actor_id,
                        created_at=now,
                    )
                )
            event_payload: JsonObject = {
                "planning_run_id": str(run.id),
                "week_start": week_start.isoformat(),
                "input_hash": input_hash,
                "ruleset_hash": ruleset.content_hash,
                "output_hash": generated.output_hash,
                "decision_count": len(generated.decisions),
                "delivery": "proposal" if proposal is not None else "direct",
            }
            if proposal is not None:
                event_payload["proposal_id"] = str(proposal.id)
            await uow.outbox.add(
                OutboxEvent(
                    id=EntityId.new(),
                    aggregate_type="PlanningRun",
                    aggregate_id=run.id,
                    event_type=(
                        "swim_coach.planning.week_proposed.v1"
                        if proposal is not None
                        else "swim_coach.planning.week_generated.v1"
                    ),
                    payload=event_payload,
                    user_id=user_id,
                    correlation_id=correlation_id,
                )
            )
            await uow.audit.add(
                AuditEvent(
                    id=EntityId.new(),
                    user_id=user_id,
                    actor_type="mcp",
                    actor_id=actor_id,
                    action=(
                        "planning.week_proposed"
                        if proposal is not None
                        else "planning.week_generated"
                    ),
                    entity_type="PlanningRun",
                    entity_id=run.id,
                    correlation_id=correlation_id,
                    after=event_payload,
                )
            )
            await uow.commit()
        return run, proposal, False

    async def _snapshot(self, user_id: UserId, week_start: date) -> PlanningContext:
        week_end = week_start + timedelta(days=6)
        history_start = week_start - timedelta(days=28)
        async with self._uow_factory() as uow:
            user = await uow.users.get(user_id)
            profile = await uow.profiles.get(user_id)
            pools = await uow.pools.list(user_id)
            goals = await uow.goals.list(user_id)
            availability_rules = await uow.availability.list(user_id)
            constraints = await uow.constraints.list(user_id)
            activities = await uow.activities.list_recent(user_id, limit=50)
            feedback_by_activity = {
                item.id: await uow.activity_data.get_feedback(user_id, item.id)
                for item in activities
            }
            normalization_facts = await uow.activity_data.list_current_normalization_facts(
                user_id, [item.id for item in activities]
            )
            normalization_by_activity = {item.activity_id: item for item in normalization_facts}
            workouts = await uow.workouts.list(user_id)
            workout_ids = [item.id for item in workouts]
            revisions = await uow.workout_revisions.list_many(user_id, workout_ids)
            schedules = await uow.workout_schedules.list(user_id, workout_ids)
        if user is None or profile is None:
            raise ResourceNotFoundError("profile")
        pool = next(
            (item for item in pools if item.active and item.is_default),
            next((item for item in pools if item.active), None),
        )
        if pool is None:
            raise DomainError("POOL_REQUIRED", "Configure an active pool before planning.")
        goal = next((item for item in goals if item.status is GoalStatus.ACTIVE), None)
        if goal is None:
            raise DomainError("GOAL_REQUIRED", "Configure an active goal before planning.")

        availability: list[AvailabilitySnapshot] = []
        for rule in availability_rules:
            target_date = week_start + timedelta(days=rule.day_of_week)
            if rule.valid_from and target_date < rule.valid_from:
                continue
            if rule.valid_until and target_date > rule.valid_until:
                continue
            if rule.pool_id is not None and rule.pool_id != pool.id:
                continue
            availability.append(
                AvailabilitySnapshot(
                    date=target_date,
                    start_local_time=rule.start_local_time.isoformat(timespec="minutes"),
                    max_duration_minutes=rule.max_duration_minutes,
                    pool_id=str(pool.id),
                )
            )
        active_constraints = tuple(
            ConstraintSnapshot(
                constraint_id=str(item.id),
                type=item.constraint_type.value,
                severity=item.severity,
                active_from=item.active_from,
                active_until=item.active_until,
            )
            for item in constraints
            if item.is_active
            and item.active_from <= week_end
            and (item.active_until is None or item.active_until >= week_start)
        )

        timezone = ZoneInfo(user.timezone)
        relevant_activities = [
            item
            for item in activities
            if history_start <= item.start_time_utc.astimezone(timezone).date() < week_start
        ]
        feedback_items: list[FeedbackSnapshot] = []
        for item in relevant_activities[:10]:
            stored = feedback_by_activity[item.id]
            evaluation = resolve_session_evaluation(normalization_by_activity.get(item.id), stored)
            if (
                evaluation.effective_rpe is None
                and evaluation.effective_feeling_score is None
                and stored is None
            ):
                continue
            feedback_items.append(
                FeedbackSnapshot(
                    activity_id=str(item.id),
                    activity_date=item.start_time_utc.astimezone(timezone).date(),
                    rpe=evaluation.effective_rpe,
                    rpe_source=(
                        evaluation.rpe_source.value if evaluation.rpe_source is not None else None
                    ),
                    feeling_score=evaluation.effective_feeling_score,
                    feeling_score_source=(
                        evaluation.feeling_score_source.value
                        if evaluation.feeling_score_source is not None
                        else None
                    ),
                    technique_rating=stored.technique_rating if stored is not None else None,
                    pain_present=stored.pain_present if stored is not None else False,
                    pain_intensity=stored.pain_intensity if stored is not None else None,
                )
            )
        feedback = tuple(feedback_items)
        revision_by_id = {item.id: item for item in revisions}
        workout_by_id = {item.id: item for item in workouts}
        schedule_by_workout = {item.workout_id: item for item in schedules}
        existing = tuple(
            ExistingSessionSnapshot(
                workout_id=str(workout.id),
                scheduled_date=schedule.scheduled_date,
                distance_m=revision_by_id[workout.current_revision_id].totals.distance_m,
                purpose=workout.purpose,
            )
            for workout in workouts
            if (schedule := schedule_by_workout.get(workout.id)) is not None
            and week_start <= schedule.scheduled_date <= week_end
            and workout.current_revision_id in revision_by_id
        )
        planned_by_week: dict[date, int] = defaultdict(int)
        for schedule in schedules:
            monday = schedule.scheduled_date - timedelta(days=schedule.scheduled_date.weekday())
            if history_start <= monday < week_start and schedule.workout_id in workout_by_id:
                planned_by_week[monday] += 1
        completed_by_week: dict[date, list[int]] = defaultdict(list)
        for activity in relevant_activities:
            local_date = activity.start_time_utc.astimezone(timezone).date()
            monday = local_date - timedelta(days=local_date.weekday())
            completed_by_week[monday].append(activity.distance.meters)
        recent_weeks = tuple(
            RecentWeekSnapshot(
                week_start=monday,
                planned_sessions=planned_by_week.get(monday, 0),
                completed_sessions=len(completed_by_week.get(monday, [])),
                completed_distance_m=sum(completed_by_week.get(monday, [])),
                adherence=(
                    float(
                        min(
                            Decimal("1"),
                            Decimal(len(completed_by_week.get(monday, [])))
                            / Decimal(planned_by_week[monday]),
                        )
                    )
                    if planned_by_week.get(monday, 0)
                    else None
                ),
            )
            for monday in sorted(set(planned_by_week) | set(completed_by_week), reverse=True)
        )
        return PlanningContext(
            user_id=str(user_id),
            week_start=week_start,
            timezone=user.timezone,
            pool_id=str(pool.id),
            pool_length_m=pool.length.meters,
            goal_id=str(goal.id),
            goal_version=goal.version,
            goal_title=goal.title,
            target_distance_m=goal.target_distance.meters,
            target_pace_seconds_per_100m=float(goal.target_pace.seconds_per_100m),
            default_sessions_per_week=profile.default_sessions_per_week,
            availability=tuple(availability),
            constraints=active_constraints,
            recent_feedback=feedback,
            recent_weeks=recent_weeks,
            existing_sessions=existing,
        )
