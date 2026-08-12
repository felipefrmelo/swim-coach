"""User-owned job health, retry controls and in-app notifications."""

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header
from pydantic import BaseModel, ConfigDict, Field

from swim_coach.domain.operations import ApiIdempotencyRecord, Job, JobStatus, Notification
from swim_coach.domain.shared.errors import DomainError, ResourceNotFoundError
from swim_coach.domain.shared.value_objects import EntityId
from swim_coach.interfaces.rest.dependencies import Authenticated, CsrfAuthenticated, Services

router = APIRouter(prefix="/api/v1/operations", tags=["operations"])
IdempotencyHeader = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=200)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class JobResponse(StrictModel):
    id: UUID
    job_type: str
    status: str
    attempts: int
    max_attempts: int
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None
    error_code: str | None
    retryable: bool

    @classmethod
    def from_domain(cls, job: Job) -> "JobResponse":
        code = job.last_error.get("code") if job.last_error else None
        return cls(
            id=job.id.value,
            job_type=job.job_type,
            status=job.status.value,
            attempts=job.attempts,
            max_attempts=job.max_attempts,
            created_at=job.created_at,
            updated_at=job.updated_at,
            finished_at=job.finished_at,
            error_code=code if isinstance(code, str) else None,
            retryable=bool(job.last_error and job.last_error.get("retryable"))
            and not bool(job.last_error and job.last_error.get("ambiguous_external_effect")),
        )


class JobMetricsResponse(StrictModel):
    counts: dict[str, int]
    oldest_active_age_seconds: int = Field(ge=0)
    dead_count: int = Field(ge=0)


class OperationsResponse(StrictModel):
    jobs: list[JobResponse]
    metrics: JobMetricsResponse


class NotificationResponse(StrictModel):
    id: UUID
    notification_type: str
    title: str
    body: str
    link: str | None
    read_at: datetime | None
    created_at: datetime

    @classmethod
    def from_domain(cls, item: Notification) -> "NotificationResponse":
        return cls(
            id=item.id.value,
            notification_type=item.notification_type,
            title=item.title,
            body=item.body,
            link=item.link,
            read_at=item.read_at,
            created_at=item.created_at,
        )


@router.get("", response_model=OperationsResponse)
async def get_operations(authenticated: Authenticated, services: Services) -> OperationsResponse:
    now = datetime.now(UTC)
    async with services.uow_factory() as uow:
        jobs = await uow.jobs.list_recent(authenticated.user.id, limit=50)
        metrics = await uow.jobs.metrics(authenticated.user.id, now)
    return OperationsResponse(
        jobs=[JobResponse.from_domain(job) for job in jobs],
        metrics=JobMetricsResponse.model_validate(metrics),
    )


@router.post("/jobs/{job_id}/retry", response_model=JobResponse)
async def retry_job(
    job_id: UUID,
    idempotency_key: IdempotencyHeader,
    authenticated: CsrfAuthenticated,
    services: Services,
) -> JobResponse:
    now = datetime.now(UTC)
    request_hash = hashlib.sha256(str(job_id).encode()).hexdigest()
    scope = f"rest:retry-job:{authenticated.user.id}"
    async with services.uow_factory() as uow:
        replay = await uow.idempotency.get(scope, idempotency_key, now)
        if replay is not None:
            if replay.request_hash != request_hash:
                raise DomainError("IDEMPOTENCY_CONFLICT", "The key was used for a different retry.")
            replay_job_id = replay.response.get("job_id")
            job = (
                await uow.jobs.get(authenticated.user.id, EntityId.parse(replay_job_id))
                if isinstance(replay_job_id, str)
                else None
            )
            if job is None:
                raise DomainError("INTERNAL_ERROR", "The retry replay is inconsistent.")
            return JobResponse.from_domain(job)
        job = await uow.jobs.get(authenticated.user.id, EntityId(job_id))
        if job is None:
            raise ResourceNotFoundError("failed job")
        if (
            job.status is not JobStatus.FAILED_TERMINAL
            or not job.last_error
            or not bool(job.last_error.get("retryable"))
            or bool(job.last_error.get("ambiguous_external_effect"))
        ):
            raise DomainError("JOB_NOT_RETRYABLE", "The job is not classified as safely retryable.")
        job = await uow.jobs.retry_failed(authenticated.user.id, EntityId(job_id), now)
        if job is None:
            raise DomainError("JOB_STATE_CONFLICT", "The job state changed before retry.")
        await uow.idempotency.add(
            ApiIdempotencyRecord(
                scope=scope,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                response_status=200,
                response={"job_id": str(job.id)},
                created_at=now,
                expires_at=now + timedelta(days=1),
            )
        )
        await uow.commit()
    return JobResponse.from_domain(job)


@router.get("/notifications", response_model=list[NotificationResponse])
async def list_notifications(
    authenticated: Authenticated, services: Services
) -> list[NotificationResponse]:
    async with services.uow_factory() as uow:
        items = await uow.notifications.list_recent(authenticated.user.id, limit=50)
    return [NotificationResponse.from_domain(item) for item in items]


@router.post("/notifications/{notification_id}/read", response_model=NotificationResponse)
async def read_notification(
    notification_id: UUID,
    authenticated: CsrfAuthenticated,
    services: Services,
) -> NotificationResponse:
    async with services.uow_factory() as uow:
        item = await uow.notifications.mark_read(
            authenticated.user.id, EntityId(notification_id), datetime.now(UTC)
        )
        if item is None:
            raise ResourceNotFoundError("notification")
        await uow.commit()
    return NotificationResponse.from_domain(item)
