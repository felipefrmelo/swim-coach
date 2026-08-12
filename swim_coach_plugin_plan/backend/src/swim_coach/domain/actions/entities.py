"""Explicit user-approved external actions and their execution records."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from enum import StrEnum

from swim_coach.domain.identity.entities import utc_now
from swim_coach.domain.shared.errors import DomainError, DomainValidationError
from swim_coach.domain.shared.types import JsonObject
from swim_coach.domain.shared.value_objects import EntityId, UserId


class ActionProposalStatus(StrEnum):
    DRAFT = "DRAFT"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    QUEUED = "QUEUED"
    EXECUTING = "EXECUTING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    NEEDS_RECONCILIATION = "NEEDS_RECONCILIATION"
    CANCELLED = "CANCELLED"


class ActionDecision(StrEnum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class ActionExecutionStatus(StrEnum):
    QUEUED = "QUEUED"
    EXECUTING = "EXECUTING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    NEEDS_RECONCILIATION = "NEEDS_RECONCILIATION"
    CANCELLED = "CANCELLED"


class ExternalWorkoutBindingStatus(StrEnum):
    NOT_CREATED = "NOT_CREATED"
    CREATING = "CREATING"
    CREATED = "CREATED"
    SCHEDULING = "SCHEDULING"
    SCHEDULED = "SCHEDULED"
    FAILED = "FAILED"
    NEEDS_RECONCILIATION = "NEEDS_RECONCILIATION"


def _canonical_json(value: object) -> bytes:
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise DomainValidationError("action payload must be canonical JSON") from exc
    return encoded.encode()


def canonical_action_hash(
    *,
    action_type: str,
    target_type: str,
    target_id: EntityId,
    target_revision_id: EntityId | None,
    payload: JsonObject,
    impact: JsonObject,
) -> str:
    """Bind approval to the exact target revision, provider payload and visible impact."""

    envelope = {
        "action_type": action_type,
        "target_type": target_type,
        "target_id": str(target_id),
        "target_revision_id": str(target_revision_id) if target_revision_id else None,
        "payload": payload,
        "impact": impact,
    }
    return hashlib.sha256(_canonical_json(envelope)).hexdigest()


@dataclass(slots=True)
class ActionProposal:
    id: EntityId
    user_id: UserId
    action_type: str
    target_type: str
    target_id: EntityId
    target_revision_id: EntityId | None
    payload: JsonObject
    impact: JsonObject
    action_hash: str
    expires_at: datetime
    status: ActionProposalStatus = ActionProposalStatus.READY_FOR_REVIEW
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    version: int = 1

    def __post_init__(self) -> None:
        if not self.action_type.strip() or not self.target_type.strip() or self.version < 1:
            raise DomainValidationError("action type, target type and version are required")
        if self.created_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise DomainValidationError("action timestamps must be timezone-aware")
        if self.expires_at <= self.created_at:
            raise DomainValidationError("action expiry must be after creation")
        expected = canonical_action_hash(
            action_type=self.action_type,
            target_type=self.target_type,
            target_id=self.target_id,
            target_revision_id=self.target_revision_id,
            payload=self.payload,
            impact=self.impact,
        )
        if self.action_hash != expected:
            raise DomainValidationError("action hash does not match the proposal")

    @classmethod
    def ready_for_review(
        cls,
        *,
        id: EntityId,
        user_id: UserId,
        action_type: str,
        target_type: str,
        target_id: EntityId,
        target_revision_id: EntityId | None,
        payload: JsonObject,
        impact: JsonObject,
        expires_at: datetime,
        created_at: datetime | None = None,
    ) -> ActionProposal:
        created = created_at or datetime.now(UTC)
        return cls(
            id=id,
            user_id=user_id,
            action_type=action_type,
            target_type=target_type,
            target_id=target_id,
            target_revision_id=target_revision_id,
            payload=payload,
            impact=impact,
            action_hash=canonical_action_hash(
                action_type=action_type,
                target_type=target_type,
                target_id=target_id,
                target_revision_id=target_revision_id,
                payload=payload,
                impact=impact,
            ),
            expires_at=expires_at,
            created_at=created,
            updated_at=created,
        )

    def expire_if_needed(self, now: datetime) -> bool:
        if now.tzinfo is None:
            raise DomainValidationError("current time must be timezone-aware")
        if (
            self.status
            in {
                ActionProposalStatus.READY_FOR_REVIEW,
                ActionProposalStatus.APPROVED,
            }
            and now >= self.expires_at
        ):
            self._transition(ActionProposalStatus.EXPIRED, now)
            return True
        return False

    def approve(self, *, action_hash: str, now: datetime) -> None:
        if self.expire_if_needed(now):
            raise DomainError("ACTION_EXPIRED", "The action proposal has expired.")
        if self.status is not ActionProposalStatus.READY_FOR_REVIEW:
            raise DomainError("ACTION_NOT_REVIEWABLE", "The action is no longer reviewable.")
        if action_hash != self.action_hash:
            raise DomainError("ACTION_TAMPERED", "The reviewed action no longer matches.")
        self._transition(ActionProposalStatus.APPROVED, now)

    def reject(self, *, action_hash: str, now: datetime) -> None:
        if self.expire_if_needed(now):
            raise DomainError("ACTION_EXPIRED", "The action proposal has expired.")
        if self.status is not ActionProposalStatus.READY_FOR_REVIEW:
            raise DomainError("ACTION_NOT_REVIEWABLE", "The action is no longer reviewable.")
        if action_hash != self.action_hash:
            raise DomainError("ACTION_TAMPERED", "The reviewed action no longer matches.")
        self._transition(ActionProposalStatus.REJECTED, now)

    def queue(self, now: datetime) -> None:
        if self.expire_if_needed(now):
            raise DomainError("ACTION_EXPIRED", "The approved action has expired.")
        self._require(ActionProposalStatus.APPROVED)
        self._transition(ActionProposalStatus.QUEUED, now)

    def start(self, now: datetime) -> None:
        self._require(ActionProposalStatus.QUEUED)
        self._transition(ActionProposalStatus.EXECUTING, now)

    def succeed(self, now: datetime) -> None:
        self._require(ActionProposalStatus.EXECUTING)
        self._transition(ActionProposalStatus.SUCCEEDED, now)

    def fail(self, now: datetime, *, ambiguous: bool = False) -> None:
        self._require(ActionProposalStatus.EXECUTING)
        self._transition(
            ActionProposalStatus.NEEDS_RECONCILIATION if ambiguous else ActionProposalStatus.FAILED,
            now,
        )

    def cancel(self, now: datetime) -> None:
        if self.status not in {
            ActionProposalStatus.DRAFT,
            ActionProposalStatus.READY_FOR_REVIEW,
            ActionProposalStatus.APPROVED,
            ActionProposalStatus.QUEUED,
        }:
            raise DomainError("ACTION_NOT_CANCELLABLE", "The action can no longer be cancelled.")
        self._transition(ActionProposalStatus.CANCELLED, now)

    def _require(self, expected: ActionProposalStatus) -> None:
        if self.status is not expected:
            raise DomainError(
                "ACTION_STATE_CONFLICT",
                "The action state changed.",
                details={"status": self.status.value},
            )

    def _transition(self, status: ActionProposalStatus, now: datetime) -> None:
        self.status = status
        self.updated_at = now
        self.version += 1


@dataclass(frozen=True, slots=True)
class ActionApproval:
    id: EntityId
    proposal_id: EntityId
    user_id: UserId
    action_hash: str
    decision: ActionDecision
    explicit_verb: str
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if len(self.action_hash) != 64 or not self.explicit_verb.strip():
            raise DomainValidationError("approval hash and explicit verb are required")


@dataclass(slots=True)
class ActionExecution:
    id: EntityId
    proposal_id: EntityId
    user_id: UserId
    idempotency_key: str
    status: ActionExecutionStatus = ActionExecutionStatus.QUEUED
    result: JsonObject | None = None
    error: JsonObject | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    version: int = 1

    def __post_init__(self) -> None:
        if not 8 <= len(self.idempotency_key) <= 200 or self.version < 1:
            raise DomainValidationError("execution idempotency key is invalid")

    def start(self, now: datetime) -> None:
        if self.status is not ActionExecutionStatus.QUEUED:
            raise DomainError("ACTION_STATE_CONFLICT", "Execution is not queued.")
        self.status = ActionExecutionStatus.EXECUTING
        self.started_at = now
        self.updated_at = now
        self.version += 1

    def succeed(self, now: datetime, result: JsonObject) -> None:
        if self.status is not ActionExecutionStatus.EXECUTING:
            raise DomainError("ACTION_STATE_CONFLICT", "Execution is not running.")
        self.status = ActionExecutionStatus.SUCCEEDED
        self.result = result
        self.error = None
        self.finished_at = now
        self.updated_at = now
        self.version += 1

    def fail(self, now: datetime, error: JsonObject, *, ambiguous: bool = False) -> None:
        if self.status is not ActionExecutionStatus.EXECUTING:
            raise DomainError("ACTION_STATE_CONFLICT", "Execution is not running.")
        self.status = (
            ActionExecutionStatus.NEEDS_RECONCILIATION
            if ambiguous
            else ActionExecutionStatus.FAILED
        )
        self.error = error
        self.finished_at = now
        self.updated_at = now
        self.version += 1


@dataclass(slots=True)
class ExternalWorkoutBinding:
    id: EntityId
    user_id: UserId
    workout_id: EntityId
    revision_id: EntityId
    provider: str
    compiled_hash: str
    status: ExternalWorkoutBindingStatus = ExternalWorkoutBindingStatus.NOT_CREATED
    external_workout_id: str | None = None
    external_schedule_id: str | None = None
    scheduled_date: date | None = None
    last_error: JsonObject | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    version: int = 1

    def __post_init__(self) -> None:
        if not self.provider.strip() or len(self.compiled_hash) != 64 or self.version < 1:
            raise DomainValidationError("external workout binding identity is invalid")

    def begin_create(self, now: datetime) -> None:
        if self.status is not ExternalWorkoutBindingStatus.NOT_CREATED:
            raise DomainError("BINDING_STATE_CONFLICT", "External workout is not new.")
        self._transition(ExternalWorkoutBindingStatus.CREATING, now)

    def mark_created(self, external_workout_id: str, now: datetime) -> None:
        if (
            self.status
            not in {
                ExternalWorkoutBindingStatus.CREATING,
                ExternalWorkoutBindingStatus.NEEDS_RECONCILIATION,
            }
            or not external_workout_id.strip()
        ):
            raise DomainError("BINDING_STATE_CONFLICT", "External workout cannot be confirmed.")
        self.external_workout_id = external_workout_id
        self.last_error = None
        self._transition(ExternalWorkoutBindingStatus.CREATED, now)

    def begin_schedule(self, now: datetime) -> None:
        if self.status is not ExternalWorkoutBindingStatus.CREATED:
            raise DomainError("BINDING_STATE_CONFLICT", "External workout is not created.")
        self._transition(ExternalWorkoutBindingStatus.SCHEDULING, now)

    def mark_scheduled(
        self, scheduled_date: date, now: datetime, *, external_schedule_id: str | None
    ) -> None:
        if self.status not in {
            ExternalWorkoutBindingStatus.SCHEDULING,
            ExternalWorkoutBindingStatus.NEEDS_RECONCILIATION,
        }:
            raise DomainError("BINDING_STATE_CONFLICT", "External workout is not scheduling.")
        self.scheduled_date = scheduled_date
        self.external_schedule_id = external_schedule_id
        self.last_error = None
        self._transition(ExternalWorkoutBindingStatus.SCHEDULED, now)

    def fail(self, now: datetime, error: JsonObject, *, ambiguous: bool = False) -> None:
        self.last_error = error
        self._transition(
            ExternalWorkoutBindingStatus.NEEDS_RECONCILIATION
            if ambiguous
            else ExternalWorkoutBindingStatus.FAILED,
            now,
        )

    def _transition(self, status: ExternalWorkoutBindingStatus, now: datetime) -> None:
        self.status = status
        self.updated_at = now
        self.version += 1
