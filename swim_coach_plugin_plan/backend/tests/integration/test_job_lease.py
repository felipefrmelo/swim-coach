from datetime import date, timedelta
from typing import cast

from sqlalchemy import select

from swim_coach.application.ports.garmin import GarminErrorCategory, GarminProviderError
from swim_coach.application.services import GarminSyncService, IdentityService
from swim_coach.domain.operations import Job, JobStatus
from swim_coach.domain.shared import CorrelationId, EntityId, UserId
from swim_coach.infrastructure.db import Database, SqlAlchemyUnitOfWorkFactory
from swim_coach.infrastructure.db.models import JobModel
from swim_coach.interfaces.worker.main import Worker


class FailingGarminSync:
    def __init__(self, error: GarminProviderError) -> None:
        self.error = error

    async def sync(
        self,
        user_id: UserId,
        *,
        trigger: str = "worker",
        from_date: date | None = None,
        force: bool = False,
    ) -> None:
        del user_id, trigger, from_date, force
        raise self.error


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


async def test_worker_retries_rate_limit_and_terminates_auth_failure(database: Database) -> None:
    uow_factory = SqlAlchemyUnitOfWorkFactory(database.session_factory)
    identity = IdentityService(
        uow_factory,
        allowed_emails=frozenset({"first@example.test"}),
        allowed_subjects=frozenset(),
    )
    user = await identity.ensure_identity(
        provider="test-oidc",
        subject="worker-garmin-user",
        email="first@example.test",
        display_name="Swimmer",
        claims_snapshot={"email_verified": True},
        correlation_id=CorrelationId.new(),
    )
    rate_limited_job = Job(
        id=EntityId.new(),
        user_id=user.id,
        job_type=Worker.GARMIN_SYNC_JOB_TYPE,
        payload={},
        idempotency_key="garmin:rate-limited",
    )
    async with uow_factory() as uow:
        await uow.jobs.add(rate_limited_job)
        await uow.commit()
    rate_limited = FailingGarminSync(
        GarminProviderError(
            GarminErrorCategory.RATE_LIMITED,
            retryable=True,
            retry_after_seconds=120,
        )
    )
    assert (
        await Worker(
            uow_factory,
            cast(GarminSyncService, rate_limited),
            worker_id="worker-rate",
        ).run_once()
        is True
    )
    async with database.session_factory() as session:
        stored = await session.get(JobModel, rate_limited_job.id.value)
        assert stored is not None
        assert stored.status == JobStatus.RETRY_SCHEDULED.value
        assert stored.attempts == 1
        assert stored.last_error_json_redacted == {
            "code": GarminErrorCategory.RATE_LIMITED.value,
            "retryable": True,
        }

    auth_job = Job(
        id=EntityId.new(),
        user_id=user.id,
        job_type=Worker.GARMIN_SYNC_JOB_TYPE,
        payload={},
        idempotency_key="garmin:auth-required",
    )
    async with uow_factory() as uow:
        await uow.jobs.add(auth_job)
        await uow.commit()
    auth_failed = FailingGarminSync(
        GarminProviderError(GarminErrorCategory.AUTH_REQUIRED, retryable=False)
    )
    assert (
        await Worker(
            uow_factory,
            cast(GarminSyncService, auth_failed),
            worker_id="worker-auth",
        ).run_once()
        is True
    )
    async with database.session_factory() as session:
        stored = await session.get(JobModel, auth_job.id.value)
        assert stored is not None
        assert stored.status == JobStatus.FAILED_TERMINAL.value
        assert stored.finished_at is not None
