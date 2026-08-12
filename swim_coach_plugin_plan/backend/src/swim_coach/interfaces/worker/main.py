"""PostgreSQL-leased worker for infrastructure and Garmin synchronization jobs."""

import asyncio
import logging
import signal
from datetime import UTC, datetime, timedelta

from swim_coach.application.ports.garmin import GarminProviderError
from swim_coach.application.ports.repositories import UnitOfWorkFactory
from swim_coach.application.services import GarminSyncService
from swim_coach.bootstrap.container import build_services
from swim_coach.domain.operations import Job
from swim_coach.domain.shared.errors import DomainError
from swim_coach.domain.shared.value_objects import UserId
from swim_coach.infrastructure.db import Database
from swim_coach.settings import get_settings

logger = logging.getLogger(__name__)


class Worker:
    """Lease jobs and apply bounded retry policy with redacted failures."""

    NOOP_JOB_TYPE = "swim_coach.operations.noop.v1"
    GARMIN_SYNC_JOB_TYPE = "garmin.sync_activities"

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory | None = None,
        garmin_sync: GarminSyncService | None = None,
        *,
        worker_id: str = "worker-p01",
        poll_interval: float = 1.0,
    ) -> None:
        self._uow_factory = uow_factory
        self._garmin_sync = garmin_sync
        self._worker_id = worker_id
        self._poll_interval = poll_interval

    async def run_once(self) -> bool:
        if self._uow_factory is None:
            return False
        job_types = {self.NOOP_JOB_TYPE}
        if self._garmin_sync is not None:
            job_types.add(self.GARMIN_SYNC_JOB_TYPE)
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
        async with self._uow_factory() as uow:
            succeeded = await uow.jobs.mark_succeeded(job.id, self._worker_id, datetime.now(UTC))
            await uow.commit()
        if not succeeded:
            logger.warning("job_lease_lost", extra={"job_id": str(job.id)})
        return succeeded

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
        await Worker(services.uow_factory, services.garmin_sync).run(stop_event)
    finally:
        await database.dispose()


def main() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
