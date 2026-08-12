"""Portable user export and deliberately staged personal-data deletion."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from dataclasses import fields, is_dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any, cast
from uuid import NAMESPACE_URL, UUID, uuid5

from swim_coach.application.ports.activity_data import ObjectStorage
from swim_coach.application.ports.repositories import UnitOfWorkFactory
from swim_coach.domain.activities import FileArtifact
from swim_coach.domain.operations import (
    AuditEvent,
    DataExport,
    DataExportStatus,
    DeletionRequest,
    DeletionRequestStatus,
    Job,
)
from swim_coach.domain.shared.errors import DomainError, ResourceNotFoundError
from swim_coach.domain.shared.types import JsonObject, JsonValue
from swim_coach.domain.shared.value_objects import CorrelationId, EntityId, UserId


class PrivacyService:
    DELETE_JOB_TYPE = "privacy.delete_user"

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        storage: ObjectStorage,
        *,
        cooling_off: timedelta = timedelta(hours=24),
        export_lifetime: timedelta = timedelta(hours=24),
    ) -> None:
        self._uow_factory = uow_factory
        self._storage = storage
        self._cooling_off = cooling_off
        self._export_lifetime = export_lifetime

    async def create_export(
        self,
        user_id: UserId,
        *,
        idempotency_key: str,
        correlation_id: CorrelationId,
    ) -> DataExport:
        now = datetime.now(UTC)
        export_id = EntityId(uuid5(NAMESPACE_URL, f"swim-coach:export:{user_id}:{idempotency_key}"))
        async with self._uow_factory() as uow:
            existing = await uow.privacy_requests.get_export(user_id, export_id)
            if existing is not None:
                return existing
            data_export = DataExport(id=export_id, user_id=user_id, created_at=now)
            await uow.privacy_requests.add_export(data_export)
            await uow.commit()
        try:
            snapshot, artifacts = await self._snapshot(user_id)
            archive = io.BytesIO()
            with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
                bundle.writestr(
                    "swim-coach-data.json",
                    json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
                )
                for artifact in artifacts:
                    payload = await self._storage.get(artifact.storage_key)
                    if hashlib.sha256(payload).hexdigest() != artifact.checksum:
                        raise DomainError(
                            "ARTIFACT_CHECKSUM_MISMATCH",
                            "An export artifact failed integrity verification.",
                        )
                    bundle.writestr(
                        f"fit/{artifact.activity_id}/{artifact.id}.fit",
                        payload,
                    )
            payload = archive.getvalue()
            checksum = hashlib.sha256(payload).hexdigest()
            storage_key = f"exports/{user_id}/{data_export.id}.zip"
            await self._storage.put_atomic(
                storage_key,
                payload,
                content_type="application/zip",
                checksum=checksum,
            )
            data_export.status = DataExportStatus.READY
            data_export.storage_key = storage_key
            data_export.checksum = checksum
            data_export.size_bytes = len(payload)
            data_export.completed_at = now
            data_export.expires_at = now + self._export_lifetime
        except Exception:
            data_export.status = DataExportStatus.FAILED
            async with self._uow_factory() as uow:
                await uow.privacy_requests.update_export(data_export)
                await uow.commit()
            raise
        async with self._uow_factory() as uow:
            await uow.privacy_requests.update_export(data_export)
            await uow.audit.add(
                AuditEvent(
                    id=EntityId.new(),
                    user_id=user_id,
                    actor_type="user",
                    actor_id=str(user_id),
                    action="privacy.export_created",
                    entity_type="data_export",
                    entity_id=data_export.id,
                    correlation_id=correlation_id,
                    after={
                        "checksum": checksum,
                        "size_bytes": len(payload),
                        "expires_at": data_export.expires_at.isoformat(),
                    },
                )
            )
            await uow.commit()
        return data_export

    async def export_payload(
        self, user_id: UserId, export_id: EntityId
    ) -> tuple[bytes, DataExport]:
        async with self._uow_factory() as uow:
            data_export = await uow.privacy_requests.get_export(user_id, export_id)
        if data_export is None or data_export.status is not DataExportStatus.READY:
            raise ResourceNotFoundError("data export")
        if data_export.expires_at is None or data_export.expires_at <= datetime.now(UTC):
            raise DomainError("EXPORT_EXPIRED", "The data export has expired.")
        if data_export.storage_key is None or data_export.checksum is None:
            raise DomainError("INTERNAL_ERROR", "The data export record is incomplete.")
        payload = await self._storage.get(data_export.storage_key)
        if hashlib.sha256(payload).hexdigest() != data_export.checksum:
            raise DomainError("ARTIFACT_CHECKSUM_MISMATCH", "The data export is corrupted.")
        return payload, data_export

    async def request_deletion(
        self,
        user_id: UserId,
        *,
        idempotency_key: str,
        correlation_id: CorrelationId,
    ) -> DeletionRequest:
        now = datetime.now(UTC)
        request_id = EntityId(
            uuid5(NAMESPACE_URL, f"swim-coach:deletion:{user_id}:{idempotency_key}")
        )
        async with self._uow_factory() as uow:
            existing = await uow.privacy_requests.get_deletion(user_id, request_id)
            if existing is not None:
                return existing
        request = DeletionRequest(
            id=request_id,
            user_id=user_id,
            status=DeletionRequestStatus.REQUESTED,
            execute_after=now + self._cooling_off,
            created_at=now,
        )
        async with self._uow_factory() as uow:
            await uow.privacy_requests.add_deletion(request)
            await uow.audit.add(
                AuditEvent(
                    id=EntityId.new(),
                    user_id=user_id,
                    actor_type="user",
                    actor_id=str(user_id),
                    action="privacy.deletion_requested",
                    entity_type="deletion_request",
                    entity_id=request.id,
                    correlation_id=correlation_id,
                    after={"execute_after": request.execute_after.isoformat()},
                )
            )
            await uow.commit()
        return request

    async def confirm_deletion(
        self,
        user_id: UserId,
        request_id: EntityId,
        confirmation: str,
        *,
        correlation_id: CorrelationId,
    ) -> DeletionRequest:
        expected = f"DELETE {request_id}"
        if confirmation != expected:
            raise DomainError("DELETION_CONFIRMATION_MISMATCH", "Deletion confirmation is invalid.")
        now = datetime.now(UTC)
        async with self._uow_factory() as uow:
            request = await uow.privacy_requests.get_deletion(user_id, request_id)
            if request is None:
                raise ResourceNotFoundError("deletion request")
            if request.status is not DeletionRequestStatus.REQUESTED:
                raise DomainError(
                    "DELETION_STATE_CONFLICT", "Deletion is not awaiting confirmation."
                )
            request.status = DeletionRequestStatus.CONFIRMED
            await uow.privacy_requests.update_deletion(request)
            await uow.privacy_requests.stage_user_deletion(user_id, now)
            await uow.jobs.add_idempotent(
                Job(
                    id=EntityId.new(),
                    user_id=None,
                    job_type=self.DELETE_JOB_TYPE,
                    payload={"user_id": str(user_id), "request_id": str(request.id)},
                    available_at=request.execute_after,
                    idempotency_key=f"privacy-delete:{request.id}",
                    max_attempts=1,
                )
            )
            await uow.audit.add(
                AuditEvent(
                    id=EntityId.new(),
                    user_id=user_id,
                    actor_type="user",
                    actor_id=str(user_id),
                    action="privacy.deletion_confirmed",
                    entity_type="deletion_request",
                    entity_id=request.id,
                    correlation_id=correlation_id,
                    after={
                        "execute_after": request.execute_after.isoformat(),
                        "sessions_revoked": True,
                        "garmin_token_revoked": True,
                        "jobs_cancelled": True,
                    },
                )
            )
            await uow.commit()
        return request

    async def execute_deletion(self, user_id: UserId, request_id: EntityId) -> None:
        now = datetime.now(UTC)
        async with self._uow_factory() as uow:
            request = await uow.privacy_requests.get_deletion(user_id, request_id)
            if request is None:
                raise ResourceNotFoundError("deletion request")
            if request.status is not DeletionRequestStatus.CONFIRMED or now < request.execute_after:
                raise DomainError("DELETION_NOT_DUE", "Deletion is not due for execution.")
            artifacts = await uow.activity_data.list_artifacts(user_id)
            export_keys = await uow.privacy_requests.list_export_keys(user_id)
            request.status = DeletionRequestStatus.EXECUTED
            request.executed_at = now
            await uow.privacy_requests.update_deletion(request)
            await uow.audit.add(
                AuditEvent(
                    id=EntityId.new(),
                    user_id=user_id,
                    actor_type="worker",
                    actor_id="privacy-delete",
                    action="privacy.deletion_executed",
                    entity_type="deletion_request",
                    entity_id=request.id,
                    correlation_id=CorrelationId.new(),
                    after={"artifact_count": len(artifacts)},
                )
            )
            if not await uow.privacy_requests.delete_user(user_id):
                raise ResourceNotFoundError("user")
            await uow.commit()
        for key in [*(artifact.storage_key for artifact in artifacts), *export_keys]:
            await self._storage.delete(key)

    async def _snapshot(self, user_id: UserId) -> tuple[JsonObject, list[FileArtifact]]:
        async with self._uow_factory() as uow:
            user = await uow.users.get(user_id)
            if user is None:
                raise ResourceNotFoundError("user")
            profile = await uow.profiles.get(user_id)
            pools = await uow.pools.list(user_id)
            availability = await uow.availability.list(user_id)
            constraints = await uow.constraints.list(user_id)
            devices = await uow.devices.list(user_id)
            goals = await uow.goals.list(user_id)
            milestones = {
                str(goal.id): await uow.goal_milestones.list(user_id, goal.id) for goal in goals
            }
            workouts = await uow.workouts.list(user_id)
            revisions = {
                str(workout.id): await uow.workout_revisions.list(user_id, workout.id)
                for workout in workouts
            }
            schedules = await uow.workout_schedules.list(
                user_id, [workout.id for workout in workouts]
            )
            activities = await uow.activities.list_all(user_id)
            activity_details: list[dict[str, Any]] = []
            for activity in activities:
                activity_details.append(
                    {
                        "activity": activity,
                        "normalization": await uow.activity_data.get_current_normalization(
                            user_id, activity.id
                        ),
                        "analysis": await uow.activity_data.get_analysis(user_id, activity.id),
                        "match": await uow.activity_data.get_match(user_id, activity.id),
                        "feedback": await uow.activity_data.get_feedback(user_id, activity.id),
                    }
                )
            artifacts = list(await uow.activity_data.list_artifacts(user_id))
            sync_runs = await uow.sync_runs.list_recent(user_id, limit=100)
            connection = await uow.garmin_connections.get(user_id)
        snapshot = cast(
            JsonObject,
            _jsonable(
                {
                    "schema_version": "1.0",
                    "exported_at": datetime.now(UTC),
                    "user": user,
                    "profile": profile,
                    "pools": pools,
                    "availability": availability,
                    "constraints": constraints,
                    "devices": devices,
                    "goals": goals,
                    "milestones": milestones,
                    "workouts": workouts,
                    "workout_revisions": revisions,
                    "workout_schedules": schedules,
                    "activities": activity_details,
                    "sync_runs": sync_runs,
                    "garmin_connection": (
                        {
                            "status": connection.status,
                            "account_label_masked": connection.account_label_masked,
                            "last_success_at": connection.last_success_at,
                        }
                        if connection
                        else None
                    ),
                    "excluded": [
                        "passwords",
                        "session_tokens",
                        "oauth_tokens",
                        "garmin_encrypted_token_bundle",
                    ],
                }
            ),
        )
        return snapshot, artifacts


def _jsonable(value: Any) -> JsonValue:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime | date | time):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, EntityId | UserId):
        return str(value)
    if isinstance(value, Enum):
        return _jsonable(value.value)
    if is_dataclass(value) and not isinstance(value, type):
        return _jsonable({field.name: getattr(value, field.name) for field in fields(value)})
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    raise TypeError(f"unsupported export value: {type(value).__name__}")
