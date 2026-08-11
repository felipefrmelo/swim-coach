from datetime import timedelta

from sqlalchemy import select

from swim_coach.domain.operations import Job, JobStatus
from swim_coach.domain.shared import EntityId
from swim_coach.infrastructure.db import Database, SqlAlchemyUnitOfWorkFactory
from swim_coach.infrastructure.db.models import JobModel
from swim_coach.interfaces.worker.main import Worker


async def test_job_lease_uses_skip_locked_and_worker_completes_noop(database: Database) -> None:
    uow_factory = SqlAlchemyUnitOfWorkFactory(database.session_factory)
    first_job = Job(
        id=EntityId.new(),
        job_type=Worker.NOOP_JOB_TYPE,
        payload={},
        idempotency_key="noop:first",
    )
    async with uow_factory() as uow:
        await uow.jobs.add(first_job)
        await uow.commit()

    first_uow = uow_factory()
    second_uow = uow_factory()
    async with first_uow, second_uow:
        first_lease = await first_uow.jobs.lease_next(
            "worker-one",
            ttl=timedelta(seconds=30),
            job_types=frozenset({Worker.NOOP_JOB_TYPE}),
        )
        second_lease = await second_uow.jobs.lease_next(
            "worker-two",
            ttl=timedelta(seconds=30),
            job_types=frozenset({Worker.NOOP_JOB_TYPE}),
        )
        assert first_lease is not None
        assert second_lease is None
        await first_uow.commit()
        await second_uow.commit()

    second_job = Job(
        id=EntityId.new(),
        job_type=Worker.NOOP_JOB_TYPE,
        payload={},
        idempotency_key="noop:second",
    )
    async with uow_factory() as uow:
        await uow.jobs.add(second_job)
        await uow.commit()

    assert await Worker(uow_factory, worker_id="worker-real").run_once() is True
    async with database.session_factory() as session:
        status = await session.scalar(
            select(JobModel.status).where(JobModel.id == second_job.id.value)
        )
    assert status == JobStatus.SUCCEEDED.value
