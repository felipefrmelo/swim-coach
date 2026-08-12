"""PostgreSQL-leased worker for infrastructure and Garmin synchronization jobs."""

import asyncio
import logging
import signal
from datetime import UTC, date, datetime, timedelta
from typing import cast

from swim_coach.application.ports.garmin import (
    GarminProviderError,
    GarminWorkoutDTO,
    GarminWorkoutProvider,
)
from swim_coach.application.ports.repositories import UnitOfWorkFactory
from swim_coach.application.services import ActivityDataService, GarminSyncService
from swim_coach.bootstrap.container import build_services
from swim_coach.domain.actions import (
    ActionExecution,
    ActionExecutionStatus,
    ActionProposal,
    ActionProposalStatus,
    ExternalWorkoutBinding,
    ExternalWorkoutBindingStatus,
)
from swim_coach.domain.operations import Job
from swim_coach.domain.shared.errors import DomainError, ResourceNotFoundError
from swim_coach.domain.shared.types import JsonObject
from swim_coach.domain.shared.value_objects import EntityId, UserId
from swim_coach.domain.workouts import PlannedWorkoutStatus
from swim_coach.infrastructure.db import Database
from swim_coach.settings import get_settings

logger = logging.getLogger(__name__)
WriteEntities = tuple[ActionProposal, ActionExecution, ExternalWorkoutBinding]


class Worker:
    """Lease jobs and apply bounded retry policy with redacted failures."""

    NOOP_JOB_TYPE = "swim_coach.operations.noop.v1"
    GARMIN_SYNC_JOB_TYPE = "garmin.sync_activities"
    GARMIN_PUBLISH_JOB_TYPE = "workout.publish_garmin"
    GARMIN_SCHEDULE_JOB_TYPE = "workout.schedule_garmin"
    ACTIVITY_FETCH_FILE_JOB_TYPE = "activity.fetch_file"

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory | None = None,
        garmin_sync: GarminSyncService | None = None,
        garmin_writer: GarminWorkoutProvider | None = None,
        garmin_write_enabled: bool = False,
        *,
        activity_data: ActivityDataService | None = None,
        worker_id: str = "worker-p01",
        poll_interval: float = 1.0,
    ) -> None:
        self._uow_factory = uow_factory
        self._garmin_sync = garmin_sync
        self._garmin_writer = garmin_writer
        self._garmin_write_enabled = garmin_write_enabled
        self._activity_data = activity_data
        self._worker_id = worker_id
        self._poll_interval = poll_interval

    async def run_once(self) -> bool:
        if self._uow_factory is None:
            return False
        job_types = {self.NOOP_JOB_TYPE}
        if self._garmin_sync is not None:
            job_types.add(self.GARMIN_SYNC_JOB_TYPE)
        if self._garmin_writer is not None:
            job_types.update({self.GARMIN_PUBLISH_JOB_TYPE, self.GARMIN_SCHEDULE_JOB_TYPE})
        if self._activity_data is not None:
            job_types.add(self.ACTIVITY_FETCH_FILE_JOB_TYPE)
        async with self._uow_factory() as uow:
            job = await uow.jobs.lease_next(
                self._worker_id,
                ttl=timedelta(minutes=15),
                job_types=frozenset(job_types),
            )
            await uow.commit()
        if job is None:
            return False
        if job.job_type == self.GARMIN_SYNC_JOB_TYPE:
            return await self._run_garmin_sync(job)
        if job.job_type == self.GARMIN_PUBLISH_JOB_TYPE:
            return await self._run_garmin_publish(job)
        if job.job_type == self.GARMIN_SCHEDULE_JOB_TYPE:
            return await self._run_garmin_schedule(job)
        if job.job_type == self.ACTIVITY_FETCH_FILE_JOB_TYPE:
            return await self._run_activity_fetch_file(job)
        async with self._uow_factory() as uow:
            succeeded = await uow.jobs.mark_succeeded(job.id, self._worker_id, datetime.now(UTC))
            await uow.commit()
        if not succeeded:
            logger.warning("job_lease_lost", extra={"job_id": str(job.id)})
        return succeeded

    async def _run_activity_fetch_file(self, job: Job) -> bool:
        if self._uow_factory is None or self._activity_data is None or job.user_id is None:
            return await self._finish_failure(job, "ACTIVITY_JOB_INVALID", retryable=False)
        raw_activity_id = job.payload.get("activity_id")
        if not isinstance(raw_activity_id, str):
            return await self._finish_failure(job, "ACTIVITY_JOB_INVALID", retryable=False)
        try:
            await self._activity_data.process(job.user_id, EntityId.parse(raw_activity_id))
        except GarminProviderError as exc:
            return await self._finish_failure(
                job,
                exc.category.value,
                retryable=exc.retryable,
                retry_after_seconds=exc.retry_after_seconds,
            )
        except DomainError as exc:
            return await self._finish_failure(
                job,
                exc.code,
                retryable=exc.code in {"FIT_FILE_UNAVAILABLE", "STORAGE_UNAVAILABLE"},
            )
        except Exception:
            logger.exception("activity_processing_internal_failure", extra={"job_id": str(job.id)})
            return await self._finish_failure(job, "ACTIVITY_PROCESSING_INTERNAL", retryable=False)
        async with self._uow_factory() as uow:
            finished = await uow.jobs.mark_succeeded(job.id, self._worker_id, datetime.now(UTC))
            await uow.commit()
        return finished

    async def _run_garmin_sync(self, job: Job) -> bool:
        if self._uow_factory is None:
            return False
        if self._garmin_sync is None or job.user_id is None:
            return await self._finish_failure(job, "GARMIN_JOB_INVALID", retryable=False)
        try:
            await self._garmin_sync.sync(UserId(job.user_id.value), trigger="worker")
        except GarminProviderError as exc:
            return await self._finish_failure(
                job,
                exc.category.value,
                retryable=exc.retryable,
                retry_after_seconds=exc.retry_after_seconds,
            )
        except DomainError as exc:
            return await self._finish_failure(
                job,
                exc.code,
                retryable=exc.code == "JOB_ALREADY_RUNNING",
                retry_after_seconds=30,
            )
        except Exception:
            logger.exception("garmin_sync_internal_failure", extra={"job_id": str(job.id)})
            return await self._finish_failure(job, "GARMIN_SYNC_INTERNAL", retryable=False)
        async with self._uow_factory() as uow:
            finished = await uow.jobs.mark_succeeded(job.id, self._worker_id, datetime.now(UTC))
            await uow.commit()
        return finished

    async def _finish_failure(
        self,
        job: Job,
        code: str,
        *,
        retryable: bool,
        retry_after_seconds: int | None = None,
    ) -> bool:
        if self._uow_factory is None:
            return False
        now = datetime.now(UTC)
        can_retry = retryable and job.attempts < job.max_attempts
        delay_seconds = retry_after_seconds or min(3600, (2**job.attempts) * 30)
        retry_at = now + timedelta(seconds=delay_seconds) if can_retry else None
        async with self._uow_factory() as uow:
            finished = await uow.jobs.mark_failed(
                job.id,
                self._worker_id,
                now,
                error={"code": code, "retryable": can_retry},
                retry_at=retry_at,
            )
            await uow.commit()
        return finished

    async def _run_garmin_publish(self, job: Job) -> bool:
        if not self._garmin_write_enabled or self._garmin_writer is None:
            return await self._finish_failure(job, "GARMIN_WRITE_DISABLED", retryable=False)
        context = await self._write_context(job)
        if context is None:
            return await self._finish_failure(job, "GARMIN_JOB_INVALID", retryable=False)
        proposal_id, binding_id = context
        try:
            proposal, execution, binding = await self._start_publish(job, proposal_id, binding_id)
            if binding.status is ExternalWorkoutBindingStatus.CREATED:
                return await self._queue_schedule(job, proposal, execution, binding)
            compiled = self._compiled_payload(proposal.payload)
            result = None
            if proposal.status is ActionProposalStatus.EXECUTING and job.attempts > 1:
                result = await self._garmin_writer.find_workout_by_source_hash(
                    proposal.user_id, compiled.source_revision_hash
                )
            if result is None:
                try:
                    result = await self._garmin_writer.create_workout(proposal.user_id, compiled)
                except GarminProviderError as exc:
                    if exc.outcome_ambiguous:
                        result = await self._garmin_writer.find_workout_by_source_hash(
                            proposal.user_id, compiled.source_revision_hash
                        )
                        if result is None:
                            return await self._mark_write_reconciliation(
                                job, proposal_id, binding_id, exc.category.value
                            )
                    else:
                        if not exc.retryable:
                            return await self._mark_write_terminal(
                                job, proposal_id, binding_id, exc.category.value
                            )
                        return await self._finish_failure(
                            job,
                            exc.category.value,
                            retryable=exc.retryable,
                            retry_after_seconds=exc.retry_after_seconds,
                        )
            await self._mark_binding_created(
                proposal.user_id, binding.id, result.external_workout_id
            )
            refreshed = await self._write_entities(proposal.user_id, proposal.id, binding.id)
            return await self._queue_schedule(job, *refreshed)
        except (DomainError, ValueError, KeyError, TypeError) as exc:
            code = exc.code if isinstance(exc, DomainError) else "GARMIN_JOB_INVALID"
            return await self._mark_write_terminal(job, proposal_id, binding_id, code)
        except Exception:
            logger.exception("garmin_publish_internal_failure", extra={"job_id": str(job.id)})
            return await self._mark_write_terminal(
                job, proposal_id, binding_id, "GARMIN_PUBLISH_INTERNAL"
            )

    async def _run_garmin_schedule(self, job: Job) -> bool:
        if not self._garmin_write_enabled or self._garmin_writer is None:
            return await self._finish_failure(job, "GARMIN_WRITE_DISABLED", retryable=False)
        context = await self._write_context(job)
        if context is None:
            return await self._finish_failure(job, "GARMIN_JOB_INVALID", retryable=False)
        proposal_id, binding_id = context
        try:
            proposal, execution, binding = await self._start_schedule(job, proposal_id, binding_id)
            if binding.external_workout_id is None:
                raise DomainError("BINDING_STATE_CONFLICT", "External workout id is missing.")
            scheduled_date = date.fromisoformat(cast(str, proposal.payload["scheduled_date"]))
            result = None
            if binding.status is ExternalWorkoutBindingStatus.SCHEDULING and job.attempts > 1:
                result = await self._garmin_writer.find_schedule(
                    proposal.user_id, binding.external_workout_id, scheduled_date
                )
            if result is None:
                try:
                    result = await self._garmin_writer.schedule_workout(
                        proposal.user_id, binding.external_workout_id, scheduled_date
                    )
                except GarminProviderError as exc:
                    if exc.outcome_ambiguous:
                        result = await self._garmin_writer.find_schedule(
                            proposal.user_id, binding.external_workout_id, scheduled_date
                        )
                        if result is None:
                            return await self._mark_write_reconciliation(
                                job, proposal_id, binding_id, exc.category.value
                            )
                    else:
                        if not exc.retryable:
                            return await self._mark_write_terminal(
                                job, proposal_id, binding_id, exc.category.value
                            )
                        return await self._finish_failure(
                            job,
                            exc.category.value,
                            retryable=exc.retryable,
                            retry_after_seconds=exc.retry_after_seconds,
                        )
            return await self._finish_schedule(
                job,
                proposal,
                execution,
                binding,
                scheduled_date,
                result.external_schedule_id,
            )
        except (DomainError, ValueError, KeyError, TypeError) as exc:
            code = exc.code if isinstance(exc, DomainError) else "GARMIN_JOB_INVALID"
            return await self._mark_write_terminal(job, proposal_id, binding_id, code)
        except Exception:
            logger.exception("garmin_schedule_internal_failure", extra={"job_id": str(job.id)})
            return await self._mark_write_terminal(
                job, proposal_id, binding_id, "GARMIN_SCHEDULE_INTERNAL"
            )

    async def _write_context(self, job: Job) -> tuple[EntityId, EntityId] | None:
        if job.user_id is None:
            return None
        try:
            return (
                EntityId.parse(cast(str, job.payload["proposal_id"])),
                EntityId.parse(cast(str, job.payload["binding_id"])),
            )
        except (KeyError, TypeError, ValueError):
            return None

    async def _write_entities(
        self, user_id: UserId, proposal_id: EntityId, binding_id: EntityId
    ) -> WriteEntities:
        if self._uow_factory is None:
            raise ResourceNotFoundError("unit_of_work")
        async with self._uow_factory() as uow:
            proposal = await uow.action_proposals.get(user_id, proposal_id)
            execution = await uow.action_executions.get_by_proposal(user_id, proposal_id)
            binding = await uow.external_workout_bindings.get(user_id, binding_id)
        if proposal is None or execution is None or binding is None:
            raise ResourceNotFoundError("garmin_write_context")
        return proposal, execution, binding

    async def _start_publish(
        self, job: Job, proposal_id: EntityId, binding_id: EntityId
    ) -> WriteEntities:
        if job.user_id is None or self._uow_factory is None:
            raise ResourceNotFoundError("garmin_write_context")
        proposal, execution, binding = await self._write_entities(
            job.user_id, proposal_id, binding_id
        )
        if proposal.status is ActionProposalStatus.QUEUED:
            proposal_version = proposal.version
            execution_version = execution.version
            binding_version = binding.version
            now = datetime.now(UTC)
            proposal.start(now)
            execution.start(now)
            binding.begin_create(now)
            async with self._uow_factory() as uow:
                await uow.action_proposals.update(proposal, expected_version=proposal_version)
                await uow.action_executions.update(execution, expected_version=execution_version)
                await uow.external_workout_bindings.update(
                    binding, expected_version=binding_version
                )
                await uow.commit()
        elif proposal.status is not ActionProposalStatus.EXECUTING:
            raise DomainError("ACTION_STATE_CONFLICT", "Publication action is not executable.")
        return await self._write_entities(job.user_id, proposal_id, binding_id)

    async def _start_schedule(
        self, job: Job, proposal_id: EntityId, binding_id: EntityId
    ) -> WriteEntities:
        if job.user_id is None or self._uow_factory is None:
            raise ResourceNotFoundError("garmin_write_context")
        proposal, execution, binding = await self._write_entities(
            job.user_id, proposal_id, binding_id
        )
        if binding.status is ExternalWorkoutBindingStatus.CREATED:
            previous_version = binding.version
            binding.begin_schedule(datetime.now(UTC))
            async with self._uow_factory() as uow:
                await uow.external_workout_bindings.update(
                    binding, expected_version=previous_version
                )
                await uow.commit()
        elif binding.status is not ExternalWorkoutBindingStatus.SCHEDULING:
            raise DomainError("BINDING_STATE_CONFLICT", "Workout is not ready to schedule.")
        if (
            proposal.status is not ActionProposalStatus.EXECUTING
            or execution.status is not ActionExecutionStatus.EXECUTING
        ):
            raise DomainError("ACTION_STATE_CONFLICT", "Publication action is not executing.")
        return await self._write_entities(job.user_id, proposal_id, binding_id)

    @staticmethod
    def _compiled_payload(payload: JsonObject) -> GarminWorkoutDTO:
        compiled_payload = payload.get("compiled_payload")
        compiled_hash = payload.get("compiled_hash")
        revision_hash = payload.get("revision_content_hash")
        source_revision_hash = payload.get("source_revision_hash", revision_hash)
        if (
            not isinstance(compiled_payload, dict)
            or not isinstance(compiled_hash, str)
            or not isinstance(revision_hash, str)
            or not isinstance(source_revision_hash, str)
        ):
            raise DomainError("GARMIN_JOB_INVALID", "Compiled Garmin payload is missing.")
        return GarminWorkoutDTO(compiled_payload, compiled_hash, source_revision_hash)

    async def _mark_binding_created(
        self, user_id: UserId, binding_id: EntityId, external_workout_id: str
    ) -> None:
        if self._uow_factory is None:
            return
        async with self._uow_factory() as uow:
            binding = await uow.external_workout_bindings.get(user_id, binding_id)
            if binding is None:
                raise ResourceNotFoundError("external_workout_binding")
            previous_version = binding.version
            binding.mark_created(external_workout_id, datetime.now(UTC))
            await uow.external_workout_bindings.update(binding, expected_version=previous_version)
            await uow.commit()

    async def _queue_schedule(
        self,
        job: Job,
        proposal: ActionProposal,
        execution: ActionExecution,
        binding: ExternalWorkoutBinding,
    ) -> bool:
        if self._uow_factory is None or job.user_id is None:
            return False
        now = datetime.now(UTC)
        schedule_job = Job(
            id=EntityId.new(),
            user_id=job.user_id,
            job_type=self.GARMIN_SCHEDULE_JOB_TYPE,
            payload={
                "proposal_id": str(proposal.id),
                "execution_id": str(execution.id),
                "binding_id": str(binding.id),
            },
            idempotency_key=f"garmin:schedule:{binding.id}:{proposal.payload['scheduled_date']}",
            max_attempts=3,
            available_at=now,
            created_at=now,
            updated_at=now,
        )
        async with self._uow_factory() as uow:
            await uow.jobs.add_idempotent(schedule_job)
            finished = await uow.jobs.mark_succeeded(job.id, self._worker_id, now)
            await uow.commit()
        return finished

    async def _finish_schedule(
        self,
        job: Job,
        proposal: ActionProposal,
        execution: ActionExecution,
        binding: ExternalWorkoutBinding,
        scheduled_date: date,
        external_schedule_id: str | None,
    ) -> bool:
        if self._uow_factory is None or job.user_id is None:
            return False
        now = datetime.now(UTC)
        proposal_version = proposal.version
        execution_version = execution.version
        binding_version = binding.version
        binding.mark_scheduled(scheduled_date, now, external_schedule_id=external_schedule_id)
        proposal.succeed(now)
        execution.succeed(
            now,
            {
                "binding_id": str(binding.id),
                "external_workout_id_masked": self._mask_external_id(
                    cast(str, binding.external_workout_id)
                ),
            },
        )
        async with self._uow_factory() as uow:
            workout = await uow.workouts.get(job.user_id, proposal.target_id)
            if workout is None:
                raise ResourceNotFoundError("workout")
            workout_version = workout.version
            workout.status = PlannedWorkoutStatus.PUBLISHED
            workout.updated_at = now
            workout.version += 1
            await uow.external_workout_bindings.update(binding, expected_version=binding_version)
            await uow.action_proposals.update(proposal, expected_version=proposal_version)
            await uow.action_executions.update(execution, expected_version=execution_version)
            await uow.workouts.update(workout, expected_version=workout_version)
            finished = await uow.jobs.mark_succeeded(job.id, self._worker_id, now)
            await uow.commit()
        return finished

    async def _mark_write_reconciliation(
        self, job: Job, proposal_id: EntityId, binding_id: EntityId, code: str
    ) -> bool:
        if self._uow_factory is None or job.user_id is None:
            return False
        proposal, execution, binding = await self._write_entities(
            job.user_id, proposal_id, binding_id
        )
        now = datetime.now(UTC)
        proposal_version = proposal.version
        execution_version = execution.version
        binding_version = binding.version
        error: JsonObject = {"code": code, "outcome_ambiguous": True}
        proposal.fail(now, ambiguous=True)
        execution.fail(now, error, ambiguous=True)
        binding.fail(now, error, ambiguous=True)
        async with self._uow_factory() as uow:
            await uow.action_proposals.update(proposal, expected_version=proposal_version)
            await uow.action_executions.update(execution, expected_version=execution_version)
            await uow.external_workout_bindings.update(binding, expected_version=binding_version)
            finished = await uow.jobs.mark_needs_reconciliation(
                job.id, self._worker_id, now, error=error
            )
            await uow.commit()
        return finished

    async def _mark_write_terminal(
        self, job: Job, proposal_id: EntityId, binding_id: EntityId, code: str
    ) -> bool:
        if self._uow_factory is None or job.user_id is None:
            return False
        proposal, execution, binding = await self._write_entities(
            job.user_id, proposal_id, binding_id
        )
        now = datetime.now(UTC)
        error: JsonObject = {"code": code, "retryable": False}
        proposal_version = proposal.version
        execution_version = execution.version
        binding_version = binding.version
        if proposal.status is ActionProposalStatus.EXECUTING:
            proposal.fail(now)
        if execution.status is ActionExecutionStatus.EXECUTING:
            execution.fail(now, error)
        if binding.status in {
            ExternalWorkoutBindingStatus.CREATING,
            ExternalWorkoutBindingStatus.SCHEDULING,
        }:
            binding.fail(now, error)
        async with self._uow_factory() as uow:
            await uow.action_proposals.update(proposal, expected_version=proposal_version)
            await uow.action_executions.update(execution, expected_version=execution_version)
            await uow.external_workout_bindings.update(binding, expected_version=binding_version)
            finished = await uow.jobs.mark_failed(
                job.id, self._worker_id, now, error=error, retry_at=None
            )
            await uow.commit()
        return finished

    @staticmethod
    def _mask_external_id(value: str) -> str:
        return f"***{value[-4:]}" if len(value) > 4 else "***"

    async def run(self, stop_event: asyncio.Event) -> None:
        logger.info("worker_started")
        while not stop_event.is_set():
            did_work = await self.run_once()
            if did_work:
                continue
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=self._poll_interval)
            except TimeoutError:
                pass
        logger.info("worker_stopped")


async def run_worker() -> None:
    """Run until SIGINT/SIGTERM while allowing in-flight shutdown cleanup."""

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)
    settings = get_settings()
    database = Database(str(settings.database_url))
    try:
        services = build_services(settings, database)
        await Worker(
            services.uow_factory,
            services.garmin_sync,
            services.garmin_writer,
            garmin_write_enabled=settings.garmin_write_enabled,
            activity_data=services.activity_data,
        ).run(stop_event)
    finally:
        await database.dispose()


def main() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
