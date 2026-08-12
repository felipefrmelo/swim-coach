"""User-scoped workout authoring, immutable revision and local scheduling use cases."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time

from swim_coach.application.ports.repositories import UnitOfWork, UnitOfWorkFactory
from swim_coach.domain.operations import AuditEvent, OutboxEvent
from swim_coach.domain.shared.errors import (
    DomainError,
    ResourceNotFoundError,
    RevisionConflictError,
)
from swim_coach.domain.shared.types import JsonObject
from swim_coach.domain.shared.value_objects import CorrelationId, EntityId, UserId
from swim_coach.domain.workouts import (
    CanonicalWorkout,
    PlannedWorkout,
    PlannedWorkoutStatus,
    WorkoutRevision,
    WorkoutSchedule,
    WorkoutTemplate,
    canonical_content_hash,
    validate_workout,
)


@dataclass(frozen=True, slots=True)
class WorkoutDetail:
    workout: PlannedWorkout
    revisions: Sequence[WorkoutRevision]
    schedule: WorkoutSchedule | None

    @property
    def current_revision(self) -> WorkoutRevision:
        current_id = self.workout.current_revision_id
        revision = next((item for item in self.revisions if item.id == current_id), None)
        if revision is None:
            raise DomainError("INTERNAL_ERROR", "Workout current revision is missing.")
        return revision


class WorkoutService:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def list_workouts(self, user_id: UserId) -> Sequence[WorkoutDetail]:
        async with self._uow_factory() as uow:
            workouts = await uow.workouts.list(user_id)
            return [
                WorkoutDetail(
                    workout=workout,
                    revisions=await uow.workout_revisions.list(user_id, workout.id),
                    schedule=await uow.workout_schedules.get(user_id, workout.id),
                )
                for workout in workouts
            ]

    async def get_workout(self, user_id: UserId, workout_id: EntityId) -> WorkoutDetail:
        async with self._uow_factory() as uow:
            return await self._get_detail(uow, user_id, workout_id)

    async def create_draft(
        self,
        user_id: UserId,
        definition: CanonicalWorkout,
        *,
        pool_id: EntityId,
        correlation_id: CorrelationId,
    ) -> WorkoutDetail:
        validation = validate_workout(definition)
        workout = PlannedWorkout(
            id=EntityId.new(),
            user_id=user_id,
            title=definition.title,
            purpose=definition.purpose,
            pool_id=pool_id,
        )
        revision = self._new_revision(workout.id, 1, definition, validation.model_dump(mode="json"))
        async with self._uow_factory() as uow:
            await self._require_matching_pool(uow, user_id, pool_id, definition.pool_length_m)
            await uow.workouts.add(workout)
            await uow.flush()
            await uow.workout_revisions.add(revision)
            await uow.flush()
            previous_version = workout.version
            workout.current_revision_id = revision.id
            workout.updated_at = datetime.now(UTC)
            workout.version += 1
            await uow.workouts.update(workout, expected_version=previous_version)
            await self._record(
                uow,
                user_id,
                workout,
                "swim_coach.workouts.draft_created.v1",
                "workouts.draft_created",
                correlation_id,
            )
            await uow.commit()
        return WorkoutDetail(workout, (revision,), None)

    async def revise(
        self,
        user_id: UserId,
        workout_id: EntityId,
        definition: CanonicalWorkout,
        *,
        expected_version: int,
        change_reason: str | None,
        correlation_id: CorrelationId,
    ) -> WorkoutDetail:
        validation = validate_workout(definition)
        async with self._uow_factory() as uow:
            detail = await self._get_detail(uow, user_id, workout_id)
            workout = detail.workout
            if workout.version != expected_version:
                raise RevisionConflictError(workout.version)
            if workout.status in {PlannedWorkoutStatus.CANCELLED, PlannedWorkoutStatus.ARCHIVED}:
                raise DomainError(
                    "VALIDATION_FAILED", "Cancelled or archived workouts cannot be revised."
                )
            await self._require_matching_pool(
                uow, user_id, workout.pool_id, definition.pool_length_m
            )
            revision_number = max(item.revision_number for item in detail.revisions) + 1
            revision = self._new_revision(
                workout.id,
                revision_number,
                definition,
                validation.model_dump(mode="json"),
                change_reason=change_reason,
            )
            await uow.workout_revisions.add(revision)
            await uow.flush()
            previous_version = workout.version
            workout.title = definition.title
            workout.purpose = definition.purpose
            workout.current_revision_id = revision.id
            workout.status = PlannedWorkoutStatus.DRAFT
            workout.updated_at = datetime.now(UTC)
            workout.version += 1
            await uow.workouts.update(workout, expected_version=previous_version)
            await self._record(
                uow,
                user_id,
                workout,
                "swim_coach.workouts.revision_created.v1",
                "workouts.revision_created",
                correlation_id,
            )
            await uow.commit()
            return WorkoutDetail(workout, (revision, *detail.revisions), detail.schedule)

    async def approve_local(
        self,
        user_id: UserId,
        workout_id: EntityId,
        *,
        expected_version: int,
        expected_content_hash: str,
        correlation_id: CorrelationId,
    ) -> WorkoutDetail:
        async with self._uow_factory() as uow:
            detail = await self._get_detail(uow, user_id, workout_id)
            workout = detail.workout
            revision = detail.current_revision
            if workout.version != expected_version:
                raise RevisionConflictError(workout.version)
            if revision.content_hash != expected_content_hash:
                raise DomainError("REVISION_CONFLICT", "The workout content changed since review.")
            if not bool(revision.validation.get("valid")):
                raise DomainError("VALIDATION_FAILED", "Only a valid workout can be approved.")
            previous_version = workout.version
            workout.approved_revision_id = revision.id
            workout.status = PlannedWorkoutStatus.APPROVED
            workout.updated_at = datetime.now(UTC)
            workout.version += 1
            await uow.workouts.update(workout, expected_version=previous_version)
            await self._record(
                uow,
                user_id,
                workout,
                "swim_coach.workouts.revision_approved.v1",
                "workouts.revision_approved",
                correlation_id,
            )
            await uow.commit()
            return WorkoutDetail(workout, detail.revisions, detail.schedule)

    async def schedule(
        self,
        user_id: UserId,
        workout_id: EntityId,
        *,
        scheduled_date: date,
        scheduled_start_time: time | None,
        timezone: str,
        pool_id: EntityId,
        expected_version: int,
        correlation_id: CorrelationId,
    ) -> WorkoutDetail:
        async with self._uow_factory() as uow:
            detail = await self._get_detail(uow, user_id, workout_id)
            workout = detail.workout
            if workout.version != expected_version:
                raise RevisionConflictError(workout.version)
            if workout.approved_revision_id != workout.current_revision_id:
                raise DomainError(
                    "APPROVAL_REQUIRED", "Approve the current revision before scheduling."
                )
            await self._require_matching_pool(
                uow, user_id, pool_id, detail.current_revision.definition.pool_length_m
            )
            schedule = WorkoutSchedule(
                id=detail.schedule.id if detail.schedule else EntityId.new(),
                workout_id=workout.id,
                scheduled_date=scheduled_date,
                scheduled_start_time=scheduled_start_time,
                timezone=timezone,
                pool_id=pool_id,
            )
            await uow.workout_schedules.upsert(schedule)
            previous_version = workout.version
            workout.pool_id = pool_id
            workout.schedule = schedule
            workout.status = PlannedWorkoutStatus.SCHEDULED
            workout.updated_at = datetime.now(UTC)
            workout.version += 1
            await uow.workouts.update(workout, expected_version=previous_version)
            await self._record(
                uow,
                user_id,
                workout,
                "swim_coach.workouts.scheduled.v1",
                "workouts.scheduled",
                correlation_id,
            )
            await uow.commit()
            return WorkoutDetail(workout, detail.revisions, schedule)

    async def list_templates(self, user_id: UserId) -> Sequence[WorkoutTemplate]:
        async with self._uow_factory() as uow:
            return await uow.workout_templates.list(user_id)

    async def create_template(
        self,
        user_id: UserId,
        definition: CanonicalWorkout,
        *,
        name: str,
        objective: str,
    ) -> WorkoutTemplate:
        validation = validate_workout(definition)
        if not validation.valid:
            raise DomainError("VALIDATION_FAILED", "Only a valid workout can become a template.")
        template = WorkoutTemplate(
            id=EntityId.new(),
            owner_user_id=user_id,
            name=name.strip(),
            objective=objective.strip(),
            tags=definition.tags,
            definition=definition,
        )
        async with self._uow_factory() as uow:
            if await uow.users.get(user_id) is None:
                raise ResourceNotFoundError("user")
            await uow.workout_templates.add(template)
            await uow.commit()
        return template

    @staticmethod
    def _new_revision(
        workout_id: EntityId,
        number: int,
        definition: CanonicalWorkout,
        validation: dict[str, object],
        *,
        change_reason: str | None = None,
    ) -> WorkoutRevision:
        result = validate_workout(definition)
        return WorkoutRevision(
            id=EntityId.new(),
            workout_id=workout_id,
            revision_number=number,
            definition=definition,
            totals=result.totals,
            validation=validation,
            content_hash=canonical_content_hash(definition),
            change_reason=change_reason,
        )

    @staticmethod
    async def _get_detail(uow: UnitOfWork, user_id: UserId, workout_id: EntityId) -> WorkoutDetail:
        workout = await uow.workouts.get(user_id, workout_id)
        if workout is None:
            raise ResourceNotFoundError("workout")
        revisions = await uow.workout_revisions.list(user_id, workout_id)
        schedule = await uow.workout_schedules.get(user_id, workout_id)
        return WorkoutDetail(workout, revisions, schedule)

    @staticmethod
    async def _require_matching_pool(
        uow: UnitOfWork, user_id: UserId, pool_id: EntityId, expected_length_m: int
    ) -> None:
        pool = await uow.pools.get(user_id, pool_id)
        if pool is None:
            raise ResourceNotFoundError("pool")
        if pool.length.meters != expected_length_m:
            raise DomainError(
                "POOL_DISTANCE_MISMATCH",
                "Workout pool length does not match the selected pool.",
                details={"expected_length_m": pool.length.meters},
            )

    @staticmethod
    async def _record(
        uow: UnitOfWork,
        user_id: UserId,
        workout: PlannedWorkout,
        event_type: str,
        action: str,
        correlation_id: CorrelationId,
    ) -> None:
        payload: JsonObject = {
            "workout_id": str(workout.id),
            "workout_version": workout.version,
            "status": workout.status.value,
        }
        await uow.outbox.add(
            OutboxEvent(
                id=EntityId.new(),
                aggregate_type="PlannedWorkout",
                aggregate_id=workout.id,
                aggregate_version=workout.version,
                event_type=event_type,
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
                action=action,
                entity_type="PlannedWorkout",
                entity_id=workout.id,
                correlation_id=correlation_id,
                after=payload,
            )
        )
