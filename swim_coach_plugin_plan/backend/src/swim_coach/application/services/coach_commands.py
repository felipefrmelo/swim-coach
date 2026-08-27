"""ChatGPT-first commands that keep revision and operation details internal."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from typing import Any

from swim_coach.application.ports.repositories import UnitOfWorkFactory
from swim_coach.application.services.garmin_upsert import GarminUpsertResult, GarminUpsertService
from swim_coach.application.services.planning import PlanningService
from swim_coach.application.services.workout_deletion import (
    WorkoutDeletionResult,
    WorkoutDeletionService,
)
from swim_coach.application.services.workouts import WorkoutDetail, WorkoutService
from swim_coach.domain.planning import PlanningPreferences
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
    ) -> None:
        self._uow_factory = uow_factory
        self._workouts = workouts
        self._garmin_upsert = garmin_upsert
        self._workout_deletion = workout_deletion
        self._planning = planning

    @property
    def garmin_write_enabled(self) -> bool:
        return self._garmin_upsert.write_enabled

    @property
    def planning_enabled(self) -> bool:
        return self._planning is not None

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
    ) -> GeneratedWeekResult:
        if self._planning is None:
            raise DomainError("PLANNING_DISABLED", "Weekly planning is disabled.")
        run, _proposal, replayed = await self._planning.propose_week(
            user_id,
            actor_id=actor_id,
            week_start=week_start,
            preferences=preferences,
            user_notes_present=False,
            correlation_id=correlation_id,
            create_proposal=False,
        )
        sessions = run.output_plan.get("sessions")
        if not isinstance(sessions, list):
            raise DomainError("INTERNAL_ERROR", "Generated week has no sessions.")
        existing = await self._workouts.list_workouts(user_id)
        created: list[EntityId] = []
        for raw in sessions:
            if not isinstance(raw, dict) or not isinstance(raw.get("workout"), dict):
                raise DomainError("INTERNAL_ERROR", "Generated session is invalid.")
            definition = CanonicalWorkout.model_validate(raw["workout"])
            target_date = date.fromisoformat(str(raw["date"]))
            target_time = time.fromisoformat(str(raw["start_local_time"]))
            content_hash = canonical_content_hash(definition)
            duplicate = next(
                (
                    item
                    for item in existing
                    if item.schedule is not None
                    and item.schedule.scheduled_date == target_date
                    and item.current_revision.content_hash == content_hash
                ),
                None,
            )
            if duplicate is not None:
                created.append(duplicate.workout.id)
                continue
            detail = await self.save_workout(
                user_id,
                definition,
                workout_id=None,
                pool_id=None,
                scheduled_date=target_date,
                scheduled_start_time=target_time,
                change_reason="Semana gerada pelo coach",
                correlation_id=correlation_id,
            )
            created.append(detail.workout.id)
        return GeneratedWeekResult(run.id, tuple(created), run.output_plan, replayed)
