from __future__ import annotations

import hashlib
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select

from swim_coach.application.ports.garmin import GarminActivityFileDTO
from swim_coach.application.services import ActivityDataService, GarminSyncService, IdentityService
from swim_coach.domain.activities import (
    ActivityInterval,
    ActivityLap,
    ActivityLength,
    ActivityNormalization,
    DataQuality,
    NormalizedActivity,
)
from swim_coach.domain.shared import CorrelationId
from swim_coach.domain.shared.errors import DomainError, ResourceNotFoundError
from swim_coach.domain.shared.value_objects import EntityId, UserId
from swim_coach.infrastructure.db import Database, SqlAlchemyUnitOfWorkFactory
from swim_coach.infrastructure.db.models import (
    ActivityAnalysisModel,
    ActivityNormalizationModel,
    FileArtifactModel,
    SessionFeedbackModel,
)
from swim_coach.infrastructure.storage import FilesystemObjectStorage
from swim_coach.interfaces.rest.activities import ActivityDetailResponse

from .test_garmin_sync import FixtureGarminProvider, no_op_user_lock


class ActivityFileProvider(FixtureGarminProvider):
    async def download_activity_file(
        self, user_id: UserId, external_activity_id: str
    ) -> GarminActivityFileDTO:
        del user_id, external_activity_id
        return GarminActivityFileDTO(b"synthetic-fit-private", "application/vnd.ant.fit")


class FixtureParser:
    parser_version = "fixture-parser:1.0.0"
    profile_version = "fixture-profile:1.0.0"

    def normalize(
        self,
        data: bytes,
        *,
        user_id: UserId,
        activity_id: EntityId,
        artifact_id: EntityId,
        input_checksum: str,
        fallback_pool_length_m: int,
    ) -> NormalizedActivity:
        assert hashlib.sha256(data).hexdigest() == input_checksum
        normalization_id = EntityId.new()
        lap = ActivityLap(
            EntityId.new(),
            normalization_id,
            0,
            Decimal(0),
            Decimal(190),
            Decimal(180),
            120,
        )
        intervals = []
        lengths = []
        for index, duration in enumerate((28, 29, 30, 31, 32, 33)):
            interval_id = EntityId.new()
            intervals.append(
                ActivityInterval(
                    interval_id,
                    normalization_id,
                    index,
                    "work",
                    Decimal(index * 30),
                    Decimal(duration),
                    Decimal(2),
                    20,
                    Decimal(duration * 5),
                    stroke_type="freestyle",
                    stroke_count=17,
                    swolf=Decimal(duration + 17),
                )
            )
            lengths.append(
                ActivityLength(
                    EntityId.new(),
                    normalization_id,
                    interval_id,
                    index,
                    fallback_pool_length_m,
                    Decimal(duration),
                    "freestyle",
                    17,
                    swolf=Decimal(duration + 17),
                )
            )
        normalization = ActivityNormalization(
            normalization_id,
            user_id,
            activity_id,
            artifact_id,
            self.parser_version,
            self.profile_version,
            input_checksum,
            fallback_pool_length_m,
            120,
            Decimal(190),
            Decimal(180),
            Decimal(180),
            6,
            Decimal(1),
            DataQuality.COMPLETE,
        )
        return NormalizedActivity(normalization, (lap,), tuple(intervals), tuple(lengths))


async def test_activity_pipeline_replay_versions_feedback_and_preserves_ownership(
    database: Database,
    tmp_path: Path,
) -> None:
    uow_factory = SqlAlchemyUnitOfWorkFactory(database.session_factory)
    identity = IdentityService(
        uow_factory,
        allowed_emails=frozenset({"first@example.test", "second@example.test"}),
        allowed_subjects=frozenset(),
    )
    user = await identity.ensure_identity(
        provider="test",
        subject="activity-owner",
        email="first@example.test",
        display_name="Swimmer",
        claims_snapshot={"email_verified": True},
        correlation_id=CorrelationId.new(),
    )
    other = await identity.ensure_identity(
        provider="test",
        subject="other-user",
        email="second@example.test",
        display_name="Other",
        claims_snapshot={"email_verified": True},
        correlation_id=CorrelationId.new(),
    )
    provider = ActivityFileProvider()
    sync = GarminSyncService(
        uow_factory,
        provider,
        no_op_user_lock,
        lookback_days=365,
        page_size=1,
    )
    await sync.sync(user.id, trigger="test")
    async with uow_factory() as uow:
        activities = await uow.activities.list_recent(user.id)
    activity = activities[0]
    service = ActivityDataService(
        uow_factory,
        provider,
        FilesystemObjectStorage(tmp_path / "artifacts"),
        FixtureParser(),
    )

    first = await service.process(user.id, activity.id)
    replay = await service.process(user.id, activity.id)

    assert first.normalized is not None
    assert first.analysis is not None
    assert replay.normalized is not None
    assert replay.normalized.normalization.id == first.normalized.normalization.id
    assert replay.analysis is not None
    assert replay.analysis.id == first.analysis.id
    assert first.analysis.metrics["fade_percent"] == "14.04"
    public_payload = ActivityDetailResponse.from_detail(first).model_dump(mode="json")
    assert public_payload["raw_fit_exposed"] is False
    assert "storage_key" not in public_payload
    assert "input_checksum" not in public_payload
    assert "synthetic-fit-private" not in str(public_payload)
    async with database.session_factory() as session:
        artifact_count = await session.scalar(select(func.count()).select_from(FileArtifactModel))
        normalization_count = await session.scalar(
            select(func.count()).select_from(ActivityNormalizationModel)
        )
        analysis_count = await session.scalar(
            select(func.count()).select_from(ActivityAnalysisModel)
        )
    assert (artifact_count, normalization_count, analysis_count) == (1, 1, 1)

    feedback = await service.record_feedback(
        user.id,
        activity.id,
        rpe=6,
        technique_rating=4,
        fatigue_rating=3,
        enjoyment_rating=5,
        pain_present=False,
        pain_location=None,
        pain_intensity=None,
        comment="Synthetic note",
        expected_version=None,
        actor_id=str(user.id),
        correlation_id=CorrelationId.new(),
    )
    assert feedback.version == 1
    async with database.session_factory() as session:
        feedback_count = await session.scalar(
            select(func.count()).select_from(SessionFeedbackModel)
        )
        analysis_count = await session.scalar(
            select(func.count()).select_from(ActivityAnalysisModel)
        )
    assert feedback_count == 1
    assert analysis_count == 2

    with pytest.raises(DomainError) as conflict:
        await service.record_feedback(
            user.id,
            activity.id,
            rpe=7,
            technique_rating=4,
            fatigue_rating=None,
            enjoyment_rating=None,
            pain_present=False,
            pain_location=None,
            pain_intensity=None,
            comment=None,
            expected_version=99,
            actor_id=str(user.id),
            correlation_id=CorrelationId.new(),
        )
    assert conflict.value.code == "REVISION_CONFLICT"

    with pytest.raises(ResourceNotFoundError):
        await service.get(other.id, activity.id)
