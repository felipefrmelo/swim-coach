"""Direct, idempotent Garmin workout upsert orchestration for MCP v2."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

from swim_coach.application.ports.repositories import UnitOfWorkFactory
from swim_coach.application.services.garmin_workout_compiler import GarminWorkoutCompiler
from swim_coach.domain.actions import ExternalWorkoutBinding
from swim_coach.domain.operations import AuditEvent, Job, OutboxEvent
from swim_coach.domain.shared.errors import DomainError, ResourceNotFoundError
from swim_coach.domain.shared.types import JsonObject
from swim_coach.domain.shared.value_objects import CorrelationId, EntityId, UserId


@dataclass(frozen=True, slots=True)
class GarminUpsertResult:
    workout_id: EntityId
    revision: int
    scheduled_date: str
    status: str
    job_id: EntityId | None
    replayed: bool
    warnings: tuple[str, ...] = ()


class GarminUpsertService:
    """Queue one stable per-workout operation without exposing action machinery."""

    JOB_TYPE = "workout.upsert_garmin"

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        *,
        write_enabled: bool,
        allow_fake_device: bool = False,
        compiler: GarminWorkoutCompiler | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._write_enabled = write_enabled
        self._allow_fake_device = allow_fake_device
        self._compiler = compiler or GarminWorkoutCompiler()

    @property
    def write_enabled(self) -> bool:
        return self._write_enabled

    async def request(
        self,
        user_id: UserId,
        workout_id: EntityId,
        *,
        device_id: EntityId | None,
        correlation_id: CorrelationId,
    ) -> GarminUpsertResult:
        if not self._write_enabled:
            raise DomainError(
                "GARMIN_WRITE_DISABLED",
                "Garmin publication is disabled in this environment.",
            )
        now = datetime.now(UTC)
        async with self._uow_factory() as uow:
            workout = await uow.workouts.get(user_id, workout_id)
            if workout is None:
                raise ResourceNotFoundError("workout")
            if (
                workout.current_revision_id is None
                or workout.current_revision_id != workout.approved_revision_id
            ):
                raise DomainError(
                    "APPROVAL_REQUIRED", "Save the current workout before publishing."
                )
            revision = await uow.workout_revisions.get(user_id, workout.current_revision_id)
            schedule = await uow.workout_schedules.get(user_id, workout.id)
            if revision is None or schedule is None:
                raise DomainError("SCHEDULE_REQUIRED", "Schedule the workout before publishing.")
            devices = [
                item for item in await uow.devices.list(user_id) if item.provider == "garmin"
            ]
            selected = next(
                (item for item in devices if device_id is not None and item.id == device_id),
                None,
            )
            if device_id is not None and selected is None:
                raise ResourceNotFoundError("device")
            selected = selected or next((item for item in devices if item.is_primary), None)
            selected = selected or (devices[0] if devices else None)
            if selected is None and not self._allow_fake_device:
                raise DomainError(
                    "GARMIN_DEVICE_REQUIRED", "Sync Garmin devices before publishing a workout."
                )
            compiled = self._compiler.compile(revision)
            binding = await uow.external_workout_bindings.get_by_workout(
                user_id, "garmin", workout.id
            )
            if (
                binding is not None
                and binding.compiled_hash == compiled.compiled_hash
                and binding.scheduled_date == schedule.scheduled_date
                and binding.status.value == "SCHEDULED"
            ):
                return GarminUpsertResult(
                    workout.id,
                    revision.revision_number,
                    schedule.scheduled_date.isoformat(),
                    "published",
                    None,
                    True,
                    compiled.warnings,
                )
            if binding is None:
                binding = ExternalWorkoutBinding(
                    id=EntityId.new(),
                    user_id=user_id,
                    workout_id=workout.id,
                    revision_id=revision.id,
                    provider="garmin",
                    compiled_hash=compiled.compiled_hash,
                    created_at=now,
                    updated_at=now,
                )
                await uow.external_workout_bindings.add(binding)
                await uow.flush()
            operation_key = (
                f"garmin:upsert:{workout.id}:{compiled.compiled_hash}:"
                f"{schedule.scheduled_date.isoformat()}"
            )
            job = Job(
                id=EntityId.new(),
                user_id=user_id,
                job_type=self.JOB_TYPE,
                payload=cast(
                    JsonObject,
                    {
                        "workout_id": str(workout.id),
                        "revision_id": str(revision.id),
                        "revision_number": revision.revision_number,
                        "binding_id": str(binding.id),
                        "compiled_hash": compiled.compiled_hash,
                        "revision_content_hash": revision.content_hash,
                        "source_revision_hash": compiled.source_revision_hash,
                        "compiled_payload": compiled.payload,
                        "warnings": list(compiled.warnings),
                        "scheduled_date": schedule.scheduled_date.isoformat(),
                        "device_id": str(selected.id) if selected is not None else None,
                    },
                ),
                idempotency_key=operation_key,
                max_attempts=3,
                available_at=now,
                created_at=now,
                updated_at=now,
            )
            stored = await uow.jobs.add_idempotent(job)
            replayed = stored.id != job.id
            event: JsonObject = {
                "workout_id": str(workout.id),
                "revision": revision.revision_number,
                "job_id": str(stored.id),
                "scheduled_date": schedule.scheduled_date.isoformat(),
                "replayed": replayed,
                "warnings": list(compiled.warnings),
            }
            await uow.outbox.add(
                OutboxEvent(
                    id=EntityId.new(),
                    aggregate_type="PlannedWorkout",
                    aggregate_id=workout.id,
                    aggregate_version=workout.version,
                    event_type="swim_coach.workouts.garmin_upsert_requested.v1",
                    payload=event,
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
                    action="workouts.garmin_upsert_requested",
                    entity_type="PlannedWorkout",
                    entity_id=workout.id,
                    correlation_id=correlation_id,
                    after=event,
                )
            )
            await uow.commit()
        return GarminUpsertResult(
            workout.id,
            revision.revision_number,
            schedule.scheduled_date.isoformat(),
            "queued",
            stored.id,
            replayed,
            compiled.warnings,
        )
