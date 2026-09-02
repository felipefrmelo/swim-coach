"""ChatGPT-first commands that keep revision and operation details internal."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time, timedelta
from typing import Any

from swim_coach.application.ports.repositories import UnitOfWorkFactory
from swim_coach.application.services.garmin_upsert import GarminUpsertResult, GarminUpsertService
from swim_coach.application.services.planning import PlanningService
from swim_coach.application.services.training_cycles import (
    AppliedPlanRevision,
    PlanDetail,
    PlanProposalResult,
    TrainingCycleService,
)
from swim_coach.application.services.workout_deletion import (
    WorkoutDeletionResult,
    WorkoutDeletionService,
)
from swim_coach.application.services.workouts import WorkoutDetail, WorkoutService
from swim_coach.domain.planning import (
    NoteAuthor,
    NoteCategory,
    NoteImportance,
    NoteScope,
    PlanDecision,
    PlanningPreferences,
    PlanNote,
    PlanReview,
    PlanSessionBinding,
    PlanStatus,
)
from swim_coach.domain.shared.errors import DomainError, ResourceNotFoundError
from swim_coach.domain.shared.value_objects import CorrelationId, EntityId, UserId
from swim_coach.domain.workouts import CanonicalWorkout, canonical_content_hash


@dataclass(frozen=True, slots=True)
class GeneratedWeekResult:
    planning_run_id: EntityId
    workout_ids: tuple[EntityId, ...]
    week: dict[str, Any]
    replayed: bool


class CoachCommandService:
    """Provide intent-level local and external commands for MCP and the PWA."""

    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory,
        workouts: WorkoutService,
        garmin_upsert: GarminUpsertService,
        workout_deletion: WorkoutDeletionService,
        planning: PlanningService | None,
        training_cycles: TrainingCycleService | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._workouts = workouts
        self._garmin_upsert = garmin_upsert
        self._workout_deletion = workout_deletion
        self._planning = planning
        self._training_cycles = training_cycles

    @property
    def garmin_write_enabled(self) -> bool:
        return self._garmin_upsert.write_enabled

    @property
    def planning_enabled(self) -> bool:
        return self._planning is not None and self._training_cycles is not None

    async def propose_training_plan(
        self,
        user_id: UserId,
        *,
        actor_id: str,
        goal_id: EntityId | None,
        title: str | None,
        start_date: date,
        duration_weeks: int,
        strategy_summary: str | None,
        correlation_id: CorrelationId,
    ) -> PlanProposalResult:
        return await self._require_cycles().propose_plan(
            user_id,
            actor_id=actor_id,
            goal_id=goal_id,
            title=title,
            start_date=start_date,
            duration_weeks=duration_weeks,
            strategy_summary=strategy_summary,
            correlation_id=correlation_id,
        )

    async def get_training_plan(
        self, user_id: UserId, plan_id: EntityId | None = None
    ) -> PlanDetail:
        return await self._require_cycles().get_plan(user_id, plan_id)

    async def review_training_plan(
        self,
        user_id: UserId,
        *,
        actor_id: str,
        plan_id: EntityId,
        week_number: int,
        correlation_id: CorrelationId,
    ) -> PlanReview:
        return await self._require_cycles().review_week(
            user_id,
            actor_id=actor_id,
            plan_id=plan_id,
            week_number=week_number,
            correlation_id=correlation_id,
        )

    async def propose_plan_revision(
        self,
        user_id: UserId,
        *,
        actor_id: str,
        plan_id: EntityId,
        review_id: EntityId,
        expected_revision: int,
        decision: PlanDecision,
        rationale: str,
        correlation_id: CorrelationId,
    ) -> PlanProposalResult:
        return await self._require_cycles().propose_revision(
            user_id,
            actor_id=actor_id,
            plan_id=plan_id,
            review_id=review_id,
            expected_revision=expected_revision,
            decision=decision,
            rationale=rationale,
            correlation_id=correlation_id,
        )

    async def apply_plan_revision(
        self,
        user_id: UserId,
        *,
        actor_id: str,
        plan_id: EntityId,
        proposal_id: EntityId,
        expected_revision: int,
        approval_hash: str,
        correlation_id: CorrelationId,
    ) -> AppliedPlanRevision:
        return await self._require_cycles().apply_revision(
            user_id,
            actor_id=actor_id,
            plan_id=plan_id,
            proposal_id=proposal_id,
            expected_revision=expected_revision,
            approval_hash=approval_hash,
            correlation_id=correlation_id,
        )

    async def add_plan_note(
        self,
        user_id: UserId,
        *,
        actor_id: str,
        plan_id: EntityId,
        scope_type: NoteScope,
        scope_ref: str,
        category: NoteCategory,
        author_type: NoteAuthor,
        text: str,
        importance: NoteImportance,
        affects_adaptation: bool,
        valid_from: date | None,
        valid_until: date | None,
        evidence_activity_ids: tuple[EntityId, ...],
        correlation_id: CorrelationId,
    ) -> PlanNote:
        return await self._require_cycles().add_note(
            user_id,
            actor_id=actor_id,
            plan_id=plan_id,
            scope_type=scope_type,
            scope_ref=scope_ref,
            category=category,
            author_type=author_type,
            text=text,
            importance=importance,
            affects_adaptation=affects_adaptation,
            valid_from=valid_from,
            valid_until=valid_until,
            evidence_activity_ids=evidence_activity_ids,
            correlation_id=correlation_id,
        )

    async def set_training_plan_status(
        self,
        user_id: UserId,
        *,
        actor_id: str,
        plan_id: EntityId,
        status: PlanStatus,
        correlation_id: CorrelationId,
    ) -> PlanStatus:
        plan = await self._require_cycles().set_status(
            user_id,
            actor_id=actor_id,
            plan_id=plan_id,
            status=status,
            correlation_id=correlation_id,
        )
        return plan.status

    async def skip_plan_session(
        self,
        user_id: UserId,
        *,
        plan_id: EntityId,
        session_intent_id: EntityId,
    ) -> PlanSessionBinding:
        return await self._require_cycles().skip_session(
            user_id, plan_id=plan_id, session_intent_id=session_intent_id
        )

    async def save_workout(
        self,
        user_id: UserId,
        definition: CanonicalWorkout,
        *,
        workout_id: EntityId | None,
        pool_id: EntityId | None,
        scheduled_date: date | None,
        scheduled_start_time: time | None,
        change_reason: str | None,
        correlation_id: CorrelationId,
    ) -> WorkoutDetail:
        selected_pool_id = pool_id
        timezone = "America/Sao_Paulo"
        async with self._uow_factory() as uow:
            user = await uow.users.get(user_id)
            pools = await uow.pools.list(user_id)
        if user is None:
            raise ResourceNotFoundError("user")
        timezone = user.timezone
        if selected_pool_id is None:
            selected = next(
                (item for item in pools if item.active and item.is_default),
                next((item for item in pools if item.active), None),
            )
            if selected is None:
                raise DomainError("POOL_REQUIRED", "Configure a pool before saving a workout.")
            selected_pool_id = selected.id

        if workout_id is None:
            detail = await self._workouts.create_draft(
                user_id,
                definition,
                pool_id=selected_pool_id,
                correlation_id=correlation_id,
            )
        else:
            current = await self._workouts.get_workout(user_id, workout_id)
            if current.current_revision.content_hash == canonical_content_hash(definition):
                detail = current
            else:
                detail = await self._workouts.revise(
                    user_id,
                    workout_id,
                    definition,
                    expected_version=current.workout.version,
                    change_reason=change_reason or "Atualizado pelo coach",
                    correlation_id=correlation_id,
                )
        if detail.workout.current_revision_id != detail.workout.approved_revision_id:
            detail = await self._workouts.approve_local(
                user_id,
                detail.workout.id,
                expected_version=detail.workout.version,
                expected_content_hash=detail.current_revision.content_hash,
                correlation_id=correlation_id,
            )
        if scheduled_date is not None and (
            detail.schedule is None
            or detail.schedule.scheduled_date != scheduled_date
            or detail.schedule.scheduled_start_time != scheduled_start_time
            or detail.schedule.pool_id != selected_pool_id
        ):
            detail = await self._workouts.schedule(
                user_id,
                detail.workout.id,
                scheduled_date=scheduled_date,
                scheduled_start_time=scheduled_start_time,
                timezone=timezone,
                pool_id=selected_pool_id,
                expected_version=detail.workout.version,
                correlation_id=correlation_id,
            )
        return detail

    async def publish_workout(
        self,
        user_id: UserId,
        workout_id: EntityId,
        *,
        scheduled_date: date | None,
        scheduled_start_time: time | None,
        device_id: EntityId | None,
        correlation_id: CorrelationId,
    ) -> GarminUpsertResult:
        detail = await self._workouts.get_workout(user_id, workout_id)
        if detail.workout.current_revision_id != detail.workout.approved_revision_id:
            detail = await self._workouts.approve_local(
                user_id,
                workout_id,
                expected_version=detail.workout.version,
                expected_content_hash=detail.current_revision.content_hash,
                correlation_id=correlation_id,
            )
        if scheduled_date is not None:
            detail = await self.save_workout(
                user_id,
                detail.current_revision.definition,
                workout_id=workout_id,
                pool_id=detail.workout.pool_id,
                scheduled_date=scheduled_date,
                scheduled_start_time=scheduled_start_time,
                change_reason=None,
                correlation_id=correlation_id,
            )
        if detail.schedule is None:
            raise DomainError(
                "SCHEDULE_REQUIRED", "Tell me the date before publishing this workout."
            )
        return await self._garmin_upsert.request(
            user_id,
            workout_id,
            device_id=device_id,
            correlation_id=correlation_id,
        )

    async def delete_workout(
        self,
        user_id: UserId,
        workout_id: EntityId,
        *,
        correlation_id: CorrelationId,
    ) -> WorkoutDeletionResult:
        return await self._workout_deletion.request(
            user_id, workout_id, correlation_id=correlation_id
        )

    async def generate_week(
        self,
        user_id: UserId,
        *,
        actor_id: str,
        week_start: date,
        preferences: PlanningPreferences,
        correlation_id: CorrelationId,
        plan_id: EntityId | None = None,
        week_number: int | None = None,
    ) -> GeneratedWeekResult:
        del actor_id, preferences
        cycles = self._require_cycles()
        detail = await cycles.get_plan(user_id, plan_id)
        if detail.revision is None:
            raise DomainError(
                "ACTIVE_PLAN_REQUIRED", "Approve an active plan before generating a week."
            )
        selected_week = week_number
        if selected_week is None:
            detailed = next(
                (
                    item
                    for item in detail.revision.document.weeks
                    if item.detail_level.value == "DETAILED"
                ),
                None,
            )
            if detailed is None:
                raise DomainError("PLAN_WEEK_NOT_DETAILED", "The plan has no detailed week.")
            selected_week = detailed.week_number
        expected_start = detail.plan.start_date + timedelta(days=(selected_week - 1) * 7)
        if expected_start != week_start:
            raise DomainError("PLAN_WEEK_MISMATCH", "week_start does not match the plan week.")
        materialized = await cycles.materialize_week(
            user_id,
            plan_id=detail.plan.id,
            expected_revision=detail.plan.current_revision,
            week_number=selected_week,
            correlation_id=correlation_id,
        )
        week = detail.revision.document.weeks[selected_week - 1]
        return GeneratedWeekResult(
            detail.revision.id,
            materialized.workout_ids,
            week.model_dump(mode="json"),
            materialized.replayed,
        )

    def _require_cycles(self) -> TrainingCycleService:
        if self._training_cycles is None:
            raise DomainError("PLANNING_DISABLED", "Training cycle planning is disabled.")
        return self._training_cycles
