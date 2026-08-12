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
    storage = FilesystemObjectStorage(tmp_path / "private")
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

    await asyncio.sleep(0.01)
    await service.execute_deletion(user.id, deletion.id)
    assert not await storage.exists(exported.storage_key)
    async with database.session_factory() as session:
        assert await session.get(AppUserModel, user.id.value) is None
        tombstone = await session.get(DeletionRequestModel, deletion.id.value)
        assert tombstone is not None
        assert tombstone.user_id is None
        assert tombstone.status == DeletionRequestStatus.EXECUTED.value
