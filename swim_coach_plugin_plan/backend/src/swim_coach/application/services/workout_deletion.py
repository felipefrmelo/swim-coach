"""Immediate local removal with idempotent asynchronous Garmin cleanup."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from swim_coach.application.ports.repositories import UnitOfWorkFactory
from swim_coach.domain.operations import AuditEvent, Job, JobStatus, OutboxEvent
from swim_coach.domain.planning import PlanSessionState
from swim_coach.domain.shared.errors import DomainError, ResourceNotFoundError
from swim_coach.domain.shared.types import JsonObject
from swim_coach.domain.shared.value_objects import CorrelationId, EntityId, UserId
from swim_coach.domain.workouts import PlannedWorkoutStatus


@dataclass(frozen=True, slots=True)
class WorkoutDeletionResult:
    workout_id: EntityId
    local_removed: bool
    calendar_removed: bool
    garmin_cleanup: str
    job_id: EntityId
    replayed: bool


class WorkoutDeletionService:
    """Hide a workout now and let the worker remove every remaining copy safely."""

    JOB_TYPE = "workout.delete_everywhere"

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    @staticmethod
    def idempotency_key(user_id: UserId, workout_id: EntityId) -> str:
        return f"workout:delete-everywhere:{user_id}:{workout_id}"

    async def request(
        self,
        user_id: UserId,
        workout_id: EntityId,
        *,
        correlation_id: CorrelationId,
    ) -> WorkoutDeletionResult:
        now = datetime.now(UTC)
        key = self.idempotency_key(user_id, workout_id)
        async with self._uow_factory() as uow:
            workout = await uow.workouts.get(user_id, workout_id)
            existing = await uow.jobs.get_by_idempotency_key(key)
            if workout is None:
                if existing is None or existing.user_id != user_id:
                    raise ResourceNotFoundError("workout")
                return self._result(workout_id, existing, replayed=True)
            if (
                workout.status is PlannedWorkoutStatus.COMPLETED
                or (await uow.activity_data.get_match_by_workout(user_id, workout_id)) is not None
            ):
                raise DomainError(
                    "WORKOUT_DELETE_COMPLETED_FORBIDDEN",
                    "Completed or activity-matched workouts cannot be deleted.",
                )
            if workout.status is PlannedWorkoutStatus.DELETING:
                if existing is None:
                    raise DomainError(
                        "WORKOUT_DELETE_STATE_CONFLICT",
                        "Workout deletion is already in progress.",
                    )
                return self._result(workout_id, existing, replayed=True)

            calendar_removed = await uow.workout_schedules.delete(user_id, workout_id)
            previous_version = workout.version
            workout.status = PlannedWorkoutStatus.DELETING
            workout.schedule = None
            workout.updated_at = now
            workout.version += 1
            await uow.workouts.update(workout, expected_version=previous_version)
            plan_binding = await uow.plan_session_bindings.get_by_workout(user_id, workout_id)
            if plan_binding is not None:
                binding_version = plan_binding.version
                plan_binding.state = PlanSessionState.CANCELLED
                plan_binding.locked_reason = "WORKOUT_DELETED"
                plan_binding.updated_at = now
                plan_binding.version += 1
                await uow.plan_session_bindings.update(
                    plan_binding, expected_version=binding_version
                )
            job = Job(
                id=EntityId.new(),
                user_id=user_id,
                job_type=self.JOB_TYPE,
                payload={"workout_id": str(workout_id)},
                idempotency_key=key,
                max_attempts=8,
                available_at=now,
                created_at=now,
                updated_at=now,
            )
            stored = await uow.jobs.add_idempotent(job)
            replayed = stored.id != job.id
            payload: JsonObject = {
                "workout_id": str(workout_id),
                "job_id": str(stored.id),
                "calendar_removed": calendar_removed,
                "plan_session_intent_id": (
                    str(plan_binding.session_intent_id) if plan_binding else None
                ),
                "replayed": replayed,
            }
            await uow.outbox.add(
                OutboxEvent(
                    id=EntityId.new(),
                    aggregate_type="PlannedWorkout",
                    aggregate_id=workout_id,
                    aggregate_version=workout.version,
                    event_type="swim_coach.workouts.deletion_requested.v1",
                    payload=payload,
                    user_id=user_id,
                    correlation_id=correlation_id,
                )
            )
            await uow.audit.add(
                AuditEvent(
                    id=EntityId.new(),
                    user_id=user_id,
                    actor_type="user",
                    actor_id=str(user_id),
                    action="workouts.delete_everywhere_requested",
                    entity_type="PlannedWorkout",
                    entity_id=workout_id,
                    correlation_id=correlation_id,
                    after=payload,
                )
            )
            await uow.commit()
        return WorkoutDeletionResult(
            workout_id=workout_id,
            local_removed=True,
            calendar_removed=calendar_removed,
            garmin_cleanup="QUEUED",
            job_id=stored.id,
            replayed=replayed,
        )

    @staticmethod
    def _result(workout_id: EntityId, job: Job, *, replayed: bool) -> WorkoutDeletionResult:
        cleanup = "COMPLETED" if job.status is JobStatus.SUCCEEDED else "QUEUED"
        if job.status in {JobStatus.FAILED_TERMINAL, JobStatus.NEEDS_RECONCILIATION}:
            cleanup = "NEEDS_ATTENTION"
        return WorkoutDeletionResult(
            workout_id=workout_id,
            local_removed=True,
            calendar_removed=True,
            garmin_cleanup=cleanup,
            job_id=job.id,
            replayed=replayed,
        )
