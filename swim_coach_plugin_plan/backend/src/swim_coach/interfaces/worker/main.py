"""PostgreSQL-leased P01 worker with no business handlers yet."""

import asyncio
import logging
import signal
from datetime import UTC, datetime, timedelta

from swim_coach.application.ports.repositories import UnitOfWorkFactory
from swim_coach.infrastructure.db import Database, SqlAlchemyUnitOfWorkFactory
from swim_coach.settings import get_settings

logger = logging.getLogger(__name__)


class Worker:
    """Lease and finish the infrastructure-only P01 no-op job type."""

    NOOP_JOB_TYPE = "swim_coach.operations.noop.v1"

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory | None = None,
        *,
        worker_id: str = "worker-p01",
        poll_interval: float = 1.0,
    ) -> None:
        self._uow_factory = uow_factory
        self._worker_id = worker_id
        self._poll_interval = poll_interval

    async def run_once(self) -> bool:
        if self._uow_factory is None:
            return False
        async with self._uow_factory() as uow:
            job = await uow.jobs.lease_next(
                self._worker_id,
                ttl=timedelta(seconds=30),
                job_types=frozenset({self.NOOP_JOB_TYPE}),
            )
            await uow.commit()
        if job is None:
            return False
        async with self._uow_factory() as uow:
            succeeded = await uow.jobs.mark_succeeded(job.id, self._worker_id, datetime.now(UTC))
            await uow.commit()
        if not succeeded:
            logger.warning("job_lease_lost", extra={"job_id": str(job.id)})
        return succeeded

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
        uow_factory = SqlAlchemyUnitOfWorkFactory(database.session_factory)
        await Worker(uow_factory).run(stop_event)
    finally:
        await database.dispose()


def main() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
