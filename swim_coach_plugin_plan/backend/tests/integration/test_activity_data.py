from __future__ import annotations

import asyncio
import hashlib
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select

import swim_coach.application.services.activity_data as activity_data_module
from swim_coach.application.ports.garmin import GarminActivityFileDTO
from swim_coach.application.services import (
    ActivityDataService,
    GarminSyncService,
    IdentityService,
    WorkoutService,
)
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
from swim_coach.domain.workouts import CanonicalWorkout
from swim_coach.infrastructure.db import Database, SqlAlchemyUnitOfWorkFactory
from swim_coach.infrastructure.db.models import (
    ActivityAnalysisModel,
    ActivityModel,
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


def test_activity_analysis_semantic_version_is_bumped() -> None:
    assert ActivityDataService.ANALYSIS_VERSION == "swim-analysis:2.0.2"


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
        fallback_pool_length_m: int | None,
    ) -> NormalizedActivity:
        assert hashlib.sha256(data).hexdigest() == input_checksum
        assert fallback_pool_length_m is not None
        normalization_id = EntityId.new()
        lap = ActivityLap(
            EntityId.new(),
            normalization_id,
            0,
            Decimal(0),
            Decimal(190),
            Decimal(180),
            120,
            moving_seconds=Decimal(170),
            swim_seconds=Decimal(168),
            rest_seconds=Decimal(5),
            stationary_seconds=Decimal(5),
            timer_pace_seconds_per_100m=Decimal(150),
            provenance={"timer_seconds": {"source": "garmin"}},
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
                    elapsed_seconds=Decimal(duration + 2),
                    timer_seconds=Decimal(duration),
                    moving_seconds=Decimal(duration - 1),
                    swim_seconds=Decimal(duration - 1),
                    stationary_seconds=Decimal(1),
                    pace_from_garmin_reported_speed_seconds_per_100m=Decimal(duration * 5 - 2),
                    moving_pace_seconds_per_100m=Decimal((duration - 1) * 5),
                    swim_pace_seconds_per_100m=Decimal((duration - 1) * 5),
                    timer_pace_seconds_per_100m=Decimal(duration * 5),
                    elapsed_pace_seconds_per_100m=Decimal((duration + 2) * 5),
                    planned_role="work",
                    provenance={"interval_type": {"source": "planned_workout"}},
                    quality_warnings=("SYNTHETIC_WARNING",),
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
                    length_type="active",
                    elapsed_seconds=Decimal(duration),
                    timer_seconds=Decimal(duration),
                    swim_seconds=Decimal(duration),
                    rest_seconds=Decimal(0),
                    pace_from_garmin_reported_speed_seconds_per_100m=Decimal(duration * 5),
                    swim_pace_seconds_per_100m=Decimal(duration * 5),
                    timer_pace_seconds_per_100m=Decimal(duration * 5),
                    elapsed_pace_seconds_per_100m=Decimal(duration * 5),
                    provenance={"length_type": {"source": "garmin"}},
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
            Decimal(170),
            6,
            Decimal(1),
            DataQuality.COMPLETE,
            swim_seconds=Decimal(168),
            rest_seconds=Decimal(5),
            stationary_seconds=Decimal(5),
            moving_pace_seconds_per_100m=Decimal("141.667"),
            swim_pace_seconds_per_100m=Decimal(140),
            timer_pace_seconds_per_100m=Decimal(150),
            session_pace_seconds_per_100m=Decimal("158.333"),
            provenance={"moving_seconds": {"source": "garmin"}},
        )
        return NormalizedActivity(normalization, (lap,), tuple(intervals), tuple(lengths))


def _single_step_workout(distance_m: int, *, title: str) -> CanonicalWorkout:
    return CanonicalWorkout.model_validate(
        {
            "schema_version": "1.0",
            "title": title,
            "sport": "POOL_SWIMMING",
            "pool_length_m": 20,
            "purpose": "ENDURANCE",
            "nodes": [
                {
                    "type": "step",
                    "id": "main",
                    "step_role": "WORK",
                    "end_condition": {"type": "distance", "meters": distance_m},
                    "target": {
                        "type": "pace_range",
                        "min_seconds_per_100m": 150,
                        "max_seconds_per_100m": 150,
                    },
                    "stroke": {"type": "freestyle"},
                }
            ],
        }
    )


async def test_activity_pipeline_replay_versions_feedback_and_preserves_ownership(
    database: Database,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
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
    storage = FilesystemObjectStorage(tmp_path / "artifacts")
    service = ActivityDataService(
        uow_factory,
        provider,
        storage,
        FixtureParser(),
    )

    real_analyze_swim = activity_data_module.analyze_swim

    def fail_analysis(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("synthetic analysis failure")

    monkeypatch.setattr(activity_data_module, "analyze_swim", fail_analysis)
    with pytest.raises(RuntimeError, match="synthetic analysis failure"):
        await service.process(user.id, activity.id)
    async with uow_factory() as uow:
        assert await uow.activity_data.get_current_normalization(user.id, activity.id) is None
    monkeypatch.setattr(activity_data_module, "analyze_swim", real_analyze_swim)

    first = await service.process(user.id, activity.id)
    replay = await service.process(user.id, activity.id)
    local_service = ActivityDataService(uow_factory, None, storage, FixtureParser())
    local_replay = await local_service.process_local(user.id, activity.id)

    assert first.normalized is not None
    assert first.analysis is not None
    assert replay.normalized is not None
    assert replay.normalized.normalization.id == first.normalized.normalization.id
    assert replay.normalized.normalization.swim_seconds == Decimal(168)
    assert replay.normalized.normalization.provenance["moving_seconds"]["source"] == "garmin"
    assert replay.normalized.intervals[0].planned_role == "work"
    assert replay.normalized.intervals[0].quality_warnings == ("SYNTHETIC_WARNING",)
    assert replay.normalized.lengths[0].length_type == "active"
    assert replay.analysis is not None
    assert replay.analysis.id == first.analysis.id
    assert local_replay.normalized is not None
    assert local_replay.normalized.normalization.id == first.normalized.normalization.id
    assert local_replay.analysis is not None
    assert local_replay.analysis.id == first.analysis.id
    assert first.analysis.metrics["fade_percent"] == "10.71"
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


async def test_matching_uses_current_revision_and_commits_with_matching_analysis(
    database: Database,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uow_factory = SqlAlchemyUnitOfWorkFactory(database.session_factory)
    identity = IdentityService(
        uow_factory,
        allowed_emails=frozenset({"first@example.test"}),
        allowed_subjects=frozenset(),
    )
    user = await identity.ensure_identity(
        provider="test",
        subject="atomic-match-owner",
        email="first@example.test",
        display_name="Swimmer",
        claims_snapshot={"email_verified": True},
        correlation_id=CorrelationId.new(),
    )
    provider = ActivityFileProvider()
    await GarminSyncService(
        uow_factory,
        provider,
        no_op_user_lock,
        lookback_days=365,
        page_size=1,
    ).sync(user.id, trigger="test")
    async with uow_factory() as uow:
        activity = (await uow.activities.list_recent(user.id))[0]
        pool = (await uow.pools.list(user.id))[0]

    workout_service = WorkoutService(uow_factory)
    obsolete = await workout_service.create_draft(
        user.id,
        _single_step_workout(2_000, title="Obsolete revision"),
        pool_id=pool.id,
        correlation_id=CorrelationId.new(),
    )
    current = await workout_service.revise(
        user.id,
        obsolete.workout.id,
        _single_step_workout(120, title="Current revision"),
        expected_version=obsolete.workout.version,
        change_reason="Match the recorded session",
        correlation_id=CorrelationId.new(),
    )
    approved = await workout_service.approve_local(
        user.id,
        current.workout.id,
        expected_version=current.workout.version,
        expected_content_hash=current.current_revision.content_hash,
        correlation_id=CorrelationId.new(),
    )
    await workout_service.schedule(
        user.id,
        approved.workout.id,
        scheduled_date=activity.start_time_utc.date(),
        scheduled_start_time=None,
        timezone="UTC",
        pool_id=pool.id,
        expected_version=approved.workout.version,
        correlation_id=CorrelationId.new(),
    )

    service = ActivityDataService(
        uow_factory,
        provider,
        FilesystemObjectStorage(tmp_path / "atomic-artifacts"),
        FixtureParser(),
    )
    real_analyze_swim = activity_data_module.analyze_swim

    def fail_analysis(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("synthetic analysis failure")

    monkeypatch.setattr(activity_data_module, "analyze_swim", fail_analysis)
    with pytest.raises(RuntimeError, match="synthetic analysis failure"):
        await service.process(user.id, activity.id)
    async with uow_factory() as uow:
        assert await uow.activity_data.get_match(user.id, activity.id) is None
        assert await uow.activity_data.get_current_normalization(user.id, activity.id) is None

    monkeypatch.setattr(activity_data_module, "analyze_swim", real_analyze_swim)
    automatic = await service.process(user.id, activity.id)
    assert automatic.match is not None
    assert automatic.match.planned_workout_id == current.workout.id
    assert automatic.analysis is not None
    assert automatic.analysis.planned_workout_id == current.workout.id
    automatic_adherence = automatic.analysis.metrics["planned_vs_actual"]
    assert isinstance(automatic_adherence, dict)
    assert automatic_adherence["planned_distance_m"] == 120

    manual_obsolete = await workout_service.create_draft(
        user.id,
        _single_step_workout(400, title="Manual obsolete revision"),
        pool_id=pool.id,
        correlation_id=CorrelationId.new(),
    )
    manual_current = await workout_service.revise(
        user.id,
        manual_obsolete.workout.id,
        _single_step_workout(140, title="Manual current revision"),
        expected_version=manual_obsolete.workout.version,
        change_reason="Use current manual context",
        correlation_id=CorrelationId.new(),
    )
    manual_match = await service.match_manually(
        user.id,
        activity.id,
        manual_current.workout.id,
        actor_id=str(user.id),
        correlation_id=CorrelationId.new(),
    )
    assert manual_match.planned_workout_id == manual_current.workout.id
    manual_detail = await service.get(user.id, activity.id)
    assert manual_detail.analysis is not None
    assert manual_detail.analysis.planned_workout_id == manual_current.workout.id
    manual_analysis_id = manual_detail.analysis.id
    manual_adherence = manual_detail.analysis.metrics["planned_vs_actual"]
    assert isinstance(manual_adherence, dict)
    assert manual_adherence["planned_distance_m"] == 140

    # Context A -> B -> A reuses the immutable analysis for A and atomically
    # moves the public pointer instead of violating the context unique index.
    await service.match_manually(
        user.id,
        activity.id,
        current.workout.id,
        actor_id=str(user.id),
        correlation_id=CorrelationId.new(),
    )
    reverted_detail = await service.get(user.id, activity.id)
    assert reverted_detail.analysis is not None
    assert automatic.analysis is not None
    assert reverted_detail.analysis.id == automatic.analysis.id
    await service.match_manually(
        user.id,
        activity.id,
        manual_current.workout.id,
        actor_id=str(user.id),
        correlation_id=CorrelationId.new(),
    )
    restored_detail = await service.get(user.id, activity.id)
    assert restored_detail.analysis is not None
    assert restored_detail.analysis.id == manual_analysis_id

    await service.record_feedback(
        user.id,
        activity.id,
        rpe=5,
        technique_rating=4,
        fatigue_rating=3,
        enjoyment_rating=4,
        pain_present=False,
        pain_location=None,
        pain_intensity=None,
        comment=None,
        expected_version=None,
        actor_id=str(user.id),
        correlation_id=CorrelationId.new(),
    )
    feedback_detail = await service.get(user.id, activity.id)
    assert feedback_detail.analysis is not None
    assert feedback_detail.analysis.planned_workout_id == manual_current.workout.id
    feedback_adherence = feedback_detail.analysis.metrics["planned_vs_actual"]
    assert isinstance(feedback_adherence, dict)
    assert feedback_adherence["planned_distance_m"] == 140

    rollback_target = await workout_service.create_draft(
        user.id,
        _single_step_workout(160, title="Rollback target"),
        pool_id=pool.id,
        correlation_id=CorrelationId.new(),
    )
    stable_analysis_id = feedback_detail.analysis.id
    monkeypatch.setattr(activity_data_module, "analyze_swim", fail_analysis)
    with pytest.raises(RuntimeError, match="synthetic analysis failure"):
        await service.match_manually(
            user.id,
            activity.id,
            rollback_target.workout.id,
            actor_id=str(user.id),
            correlation_id=CorrelationId.new(),
        )
    rolled_back = await service.get(user.id, activity.id)
    assert rolled_back.match is not None
    assert rolled_back.match.planned_workout_id == manual_current.workout.id
    assert rolled_back.analysis is not None
    assert rolled_back.analysis.id == stable_analysis_id
    assert rolled_back.analysis.planned_workout_id == manual_current.workout.id


async def test_concurrent_activity_processing_reuses_artifact_normalization_and_analysis(
    database: Database,
    tmp_path: Path,
) -> None:
    uow_factory = SqlAlchemyUnitOfWorkFactory(database.session_factory)
    identity = IdentityService(
        uow_factory,
        allowed_emails=frozenset({"first@example.test"}),
        allowed_subjects=frozenset(),
    )
    user = await identity.ensure_identity(
        provider="test",
        subject="concurrent-activity-owner",
        email="first@example.test",
        display_name="Concurrent swimmer",
        claims_snapshot={"email_verified": True},
        correlation_id=CorrelationId.new(),
    )
    provider = ActivityFileProvider()
    await GarminSyncService(
        uow_factory,
        provider,
        no_op_user_lock,
        lookback_days=365,
        page_size=1,
    ).sync(user.id, trigger="test")
    async with uow_factory() as uow:
        activity = (await uow.activities.list_recent(user.id))[0]

    service = ActivityDataService(
        uow_factory,
        provider,
        FilesystemObjectStorage(tmp_path / "concurrent-artifacts"),
        FixtureParser(),
    )
    first, second = await asyncio.gather(
        service.process(user.id, activity.id),
        service.process(user.id, activity.id),
    )

    assert first.normalized is not None and second.normalized is not None
    assert first.analysis is not None and second.analysis is not None
    assert first.normalized.normalization.id == second.normalized.normalization.id
    assert first.analysis.id == second.analysis.id
    async with database.session_factory() as session:
        artifact_count = await session.scalar(select(func.count()).select_from(FileArtifactModel))
        normalization_count = await session.scalar(
            select(func.count()).select_from(ActivityNormalizationModel)
        )
        analysis_count = await session.scalar(
            select(func.count()).select_from(ActivityAnalysisModel)
        )
        stored_activity = await session.get(ActivityModel, activity.id.value)
    assert (artifact_count, normalization_count, analysis_count) == (1, 1, 1)
    assert stored_activity is not None
    assert stored_activity.current_normalization_id == first.normalized.normalization.id.value
    assert stored_activity.current_analysis_id == first.analysis.id.value
    async with uow_factory() as uow:
        with pytest.raises(DomainError, match="changed"):
            await uow.activity_data.promote_normalization(
                user.id,
                activity.id,
                EntityId.new(),
                first.analysis.id,
            )
