"""Job, outbox, audit and idempotency domain records."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from swim_coach.domain.identity.entities import utc_now
from swim_coach.domain.shared.errors import DomainValidationError
from swim_coach.domain.shared.types import JsonObject
from swim_coach.domain.shared.value_objects import CorrelationId, EntityId, UserId


class JobStatus(StrEnum):
    QUEUED = "QUEUED"
    LEASED = "LEASED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    RETRY_SCHEDULED = "RETRY_SCHEDULED"
    FAILED_TERMINAL = "FAILED_TERMINAL"
    NEEDS_RECONCILIATION = "NEEDS_RECONCILIATION"


@dataclass(slots=True)
class Job:
    id: EntityId
    job_type: str
    payload: JsonObject
    user_id: UserId | None = None
    status: JobStatus = JobStatus.QUEUED
    priority: int = 0
    available_at: datetime = field(default_factory=utc_now)
    attempts: int = 0
    max_attempts: int = 5
    idempotency_key: str | None = None
    locked_by: str | None = None
    locked_at: datetime | None = None
    heartbeat_at: datetime | None = None
    lease_expires_at: datetime | None = None
    last_error: JsonObject | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    finished_at: datetime | None = None
    version: int = 1

    def __post_init__(self) -> None:
        if not self.job_type.strip() or self.max_attempts < 1 or self.attempts < 0:
            raise DomainValidationError("job type and valid attempt limits are required")

    def lease(self, worker_id: str, *, ttl: timedelta) -> None:
        now = datetime.now(UTC)
        if self.status not in {JobStatus.QUEUED, JobStatus.RETRY_SCHEDULED}:
            raise DomainValidationError("only queued jobs can be leased")
        if ttl <= timedelta(0):
            raise DomainValidationError("job lease TTL must be positive")
        self.status = JobStatus.LEASED
        self.locked_by = worker_id
        self.locked_at = now
        self.heartbeat_at = now
        self.lease_expires_at = now + ttl
        self.attempts += 1
        self.updated_at = now
        self.version += 1


@dataclass(slots=True)
class OutboxEvent:
    id: EntityId
    aggregate_type: str
    aggregate_id: EntityId
    event_type: str
    payload: JsonObject
    user_id: UserId | None
    correlation_id: CorrelationId
    aggregate_version: int = 1
    causation_id: EntityId | None = None
    occurred_at: datetime = field(default_factory=utc_now)
    published_at: datetime | None = None
    attempts: int = 0
    last_error: str | None = None

    def __post_init__(self) -> None:
        if not self.event_type.startswith("swim_coach.") or not self.event_type.endswith(".v1"):
            raise DomainValidationError("event type must use the versioned swim_coach namespace")


@dataclass(slots=True)
class AuditEvent:
    id: EntityId
    user_id: UserId | None
    actor_type: str
    actor_id: str
    action: str
    entity_type: str
    entity_id: EntityId | None
    correlation_id: CorrelationId
    before: JsonObject | None = None
    after: JsonObject | None = None
    ip_hash: str | None = None
    user_agent_summary: str | None = None
    created_at: datetime = field(default_factory=utc_now)


@dataclass(slots=True)
class ApiIdempotencyRecord:
    scope: str
    idempotency_key: str
    request_hash: str
    response_status: int
    response: JsonObject
    created_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        if self.created_at >= self.expires_at:
            raise DomainValidationError("idempotency expiry must be after creation")


@dataclass(frozen=True, slots=True)
class McpToolInvocation:
    """Sanitized observability record; arguments are retained only as a digest."""

    id: EntityId
    user_id: UserId
    tool_name: str
    request_id: str
    args_hash: str
    outcome: str
    latency_ms: int
    error_code: str | None = None
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not self.tool_name.strip() or not self.request_id.strip():
            raise DomainValidationError("MCP invocation identity is required")
        if len(self.args_hash) != 64:
            raise DomainValidationError("MCP invocation arguments require a SHA-256 digest")
        if self.outcome not in {"OK", "NOT_FOUND", "PARTIAL", "FAILED"}:
            raise DomainValidationError("MCP invocation outcome is invalid")
        if self.latency_ms < 0:
            raise DomainValidationError("MCP invocation latency cannot be negative")
