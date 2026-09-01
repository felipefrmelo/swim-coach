import asyncio
import io
import json
import zipfile
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from swim_coach.application.services import IdentityService, PrivacyService
from swim_coach.domain.identity import UserStatus
from swim_coach.domain.operations import DeletionRequestStatus
from swim_coach.domain.shared import CorrelationId, DomainError
from swim_coach.infrastructure.db import Database, SqlAlchemyUnitOfWorkFactory
from swim_coach.infrastructure.db.models import AppUserModel, DeletionRequestModel, JobModel
from swim_coach.infrastructure.storage import FilesystemObjectStorage


class _FailOnceOnNthDeleteStorage(FilesystemObjectStorage):
    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self._delete_calls_until_failure: int | None = None

    def fail_once_on_delete(self, call_number: int) -> None:
        self._delete_calls_until_failure = call_number

    async def delete(self, key: str) -> None:
        if self._delete_calls_until_failure is not None:
            self._delete_calls_until_failure -= 1
            if self._delete_calls_until_failure == 0:
                self._delete_calls_until_failure = None
                raise OSError("synthetic private-storage failure")
        await super().delete(key)


async def test_export_replay_and_staged_deletion_are_owned_and_recoverable(
    database: Database, tmp_path: Path
) -> None:
    uow_factory = SqlAlchemyUnitOfWorkFactory(database.session_factory)
    identity = IdentityService(
        uow_factory,
        allowed_emails=frozenset({"first@example.test"}),
        allowed_subjects=frozenset(),
    )
    user = await identity.ensure_identity(
        provider="test-oidc",
        subject="privacy-user",
        email="first@example.test",
        display_name="Swimmer",
        claims_snapshot={"email_verified": True},
        correlation_id=CorrelationId.new(),
    )
    storage = _FailOnceOnNthDeleteStorage(tmp_path / "private")
    service = PrivacyService(
        uow_factory,
        storage,
        cooling_off=timedelta(milliseconds=1),
    )

    exported = await service.create_export(
        user.id,
        idempotency_key="privacy-export-one",
        correlation_id=CorrelationId.new(),
    )
    replay = await service.create_export(
        user.id,
        idempotency_key="privacy-export-one",
        correlation_id=CorrelationId.new(),
    )
    payload, _ = await service.export_payload(user.id, exported.id)
    assert replay.id == exported.id
    with zipfile.ZipFile(io.BytesIO(payload)) as bundle:
        snapshot = json.loads(bundle.read("swim-coach-data.json"))
    assert snapshot["user"]["email"] == "first@example.test"
    assert "garmin_encrypted_token_bundle" in snapshot["excluded"]
    assert exported.storage_key is not None
    second_export = await service.create_export(
        user.id,
        idempotency_key="privacy-export-two",
        correlation_id=CorrelationId.new(),
    )
    assert second_export.storage_key is not None

    deletion = await service.request_deletion(
        user.id,
        idempotency_key="privacy-delete-one",
        correlation_id=CorrelationId.new(),
    )
    repeated_deletion = await service.request_deletion(
        user.id,
        idempotency_key="privacy-delete-one",
        correlation_id=CorrelationId.new(),
    )
    assert repeated_deletion.id == deletion.id
    with pytest.raises(DomainError, match="confirmation"):
        await service.confirm_deletion(
            user.id,
            deletion.id,
            "DELETE something-else",
            correlation_id=CorrelationId.new(),
        )
    confirmed = await service.confirm_deletion(
        user.id,
        deletion.id,
        f"DELETE {deletion.id}",
        correlation_id=CorrelationId.new(),
    )
    assert confirmed.status is DeletionRequestStatus.CONFIRMED
    async with database.session_factory() as session:
        stored_user = await session.get(AppUserModel, user.id.value)
        deletion_job = await session.scalar(
            select(JobModel).where(JobModel.job_type == PrivacyService.DELETE_JOB_TYPE)
        )
        assert stored_user is not None and stored_user.status == UserStatus.DISABLED.value
        assert deletion_job is not None and deletion_job.user_id is None
        assert deletion_job.max_attempts == 5

    await asyncio.sleep(0.01)
    storage.fail_once_on_delete(2)
    with pytest.raises(DomainError) as storage_failure:
        await service.execute_deletion(user.id, deletion.id)
    assert storage_failure.value.code == "PRIVACY_STORAGE_DELETE_FAILED"
    remaining_objects = [
        await storage.exists(exported.storage_key),
        await storage.exists(second_export.storage_key),
    ]
    assert remaining_objects.count(True) == 1
    async with database.session_factory() as session:
        retained_user = await session.get(AppUserModel, user.id.value)
        retained_request = await session.get(DeletionRequestModel, deletion.id.value)
        assert retained_user is not None
        assert retained_request is not None
        assert retained_request.user_id == user.id.value
        assert retained_request.status == DeletionRequestStatus.CONFIRMED.value

    # Blob deletion is idempotent: retrying starts from the retained metadata,
    # tolerates the object already removed by the first attempt, then commits
    # the destructive relational delete only after every remaining key is gone.
    await service.execute_deletion(user.id, deletion.id)
    assert not await storage.exists(exported.storage_key)
    assert not await storage.exists(second_export.storage_key)
    async with database.session_factory() as session:
        assert await session.get(AppUserModel, user.id.value) is None
        tombstone = await session.get(DeletionRequestModel, deletion.id.value)
        assert tombstone is not None
        assert tombstone.user_id is None
        assert tombstone.status == DeletionRequestStatus.EXECUTED.value
