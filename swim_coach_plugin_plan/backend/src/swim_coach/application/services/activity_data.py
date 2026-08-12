"""FIT artifact ingestion, normalization, analytics, matching and feedback workflows."""

from __future__ import annotations

import hashlib
import io
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from swim_coach.application.ports.activity_data import FitActivityParser, ObjectStorage
from swim_coach.application.ports.garmin import GarminProvider
from swim_coach.application.ports.repositories import UnitOfWorkFactory
from swim_coach.domain.activities import (
    ActivityAnalysis,
    FileArtifact,
    NormalizedActivity,
    SessionFeedback,
    WorkoutExecutionMatch,
    analyze_swim,
)
from swim_coach.domain.garmin import Activity
from swim_coach.domain.operations import ApiIdempotencyRecord, AuditEvent
from swim_coach.domain.shared.errors import DomainError, ResourceNotFoundError
from swim_coach.domain.shared.types import JsonObject
from swim_coach.domain.shared.value_objects import CorrelationId, EntityId, UserId


@dataclass(frozen=True, slots=True)
class ActivityDetail:
    activity: Activity
    normalized: NormalizedActivity | None
    analysis: ActivityAnalysis | None
    match: WorkoutExecutionMatch | None
    feedback: SessionFeedback | None


class ActivityDataService:
    ANALYSIS_VERSION = "swim-analysis:1.0.0"
    MAX_FIT_BYTES = 50 * 1024 * 1024

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        provider: GarminProvider | None,
        storage: ObjectStorage,
        parser: FitActivityParser,
    ) -> None:
        self._uow_factory = uow_factory
        self._provider = provider
        self._storage = storage
        self._parser = parser

    @classmethod
    def _extract_fit(cls, content: bytes, content_type: str) -> bytes:
        if content_type == "application/vnd.ant.fit":
            if len(content) > cls.MAX_FIT_BYTES:
                raise DomainError("FIT_FILE_INVALID", "FIT file exceeds the size limit.")
            return content
        if content_type != "application/zip" or not zipfile.is_zipfile(io.BytesIO(content)):
            raise DomainError("FIT_FILE_INVALID", "Garmin activity artifact is not FIT or ZIP.")
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            candidates = [
                item
                for item in archive.infolist()
                if not item.is_dir()
                and item.filename.casefold().endswith(".fit")
                and ".." not in item.filename.replace("\\", "/").split("/")
            ]
            if len(candidates) != 1:
                raise DomainError("FIT_FILE_INVALID", "Garmin ZIP must contain exactly one FIT.")
            candidate = candidates[0]
            if candidate.file_size <= 0 or candidate.file_size > cls.MAX_FIT_BYTES:
                raise DomainError(
                    "FIT_FILE_INVALID", "FIT file is empty or exceeds the size limit."
                )
            data = archive.read(candidate)
        if len(data) != candidate.file_size:
            raise DomainError("FIT_FILE_INVALID", "FIT extraction size did not match metadata.")
        return data

    async def process(self, user_id: UserId, activity_id: EntityId) -> ActivityDetail:
        if self._provider is None:
            raise DomainError("GARMIN_NOT_CONFIGURED", "Garmin FIT download is not configured.")
        async with self._uow_factory() as uow:
            activity = await uow.activities.get(user_id, activity_id)
        if activity is None:
            raise ResourceNotFoundError("activity")
        downloaded = await self._provider.download_activity_file(
            user_id, activity.external_activity_id
        )
        fit_data = self._extract_fit(downloaded.content, downloaded.content_type)
        checksum = hashlib.sha256(fit_data).hexdigest()
        source_hash = hashlib.sha256(activity.external_activity_id.encode()).hexdigest()
        storage_key = f"garmin/{user_id}/activities/{activity.id}/{checksum}.fit"
        stored = await self._storage.put_atomic(
            storage_key,
            fit_data,
            content_type="application/vnd.ant.fit",
            checksum=checksum,
        )
        async with self._uow_factory() as uow:
            artifact = await uow.activity_data.get_artifact_by_checksum(
                user_id, activity.id, checksum, "fit"
            )
            if artifact is None:
                artifact = FileArtifact(
                    id=EntityId.new(),
                    user_id=user_id,
                    activity_id=activity.id,
                    provider="garmin",
                    artifact_type="fit",
                    storage_key=stored.key,
                    content_type=stored.content_type,
                    size_bytes=stored.size_bytes,
                    checksum=stored.checksum,
                    source_external_id_hash=source_hash,
                )
                await uow.activity_data.add_artifact(artifact)
                await uow.commit()
        pool_length_m = activity.pool_length.meters if activity.pool_length else 20
        normalized = self._parser.normalize(
            fit_data,
            user_id=user_id,
            activity_id=activity.id,
            artifact_id=artifact.id,
            input_checksum=checksum,
            fallback_pool_length_m=pool_length_m,
        )
        async with self._uow_factory() as uow:
            inserted = await uow.activity_data.save_normalization(normalized)
            selected: NormalizedActivity | None
            if inserted:
                await uow.flush()
                selected = normalized
            else:
                selected = await uow.activity_data.get_normalization_by_input(
                    user_id,
                    activity.id,
                    self._parser.parser_version,
                    checksum,
                )
                if selected is None:
                    raise DomainError("FIT_REPROCESS_CONFLICT", "Normalization conflict occurred.")
            await uow.activity_data.promote_normalization(
                user_id, activity.id, selected.normalization.id
            )
            await uow.commit()
        match = await self._match_automatically(user_id, activity, selected)
        async with self._uow_factory() as uow:
            feedback = await uow.activity_data.get_feedback(user_id, activity.id)
            existing_analysis = await uow.activity_data.get_analysis(user_id, activity.id)
            analysis_version = (
                f"{self.ANALYSIS_VERSION}|feedback:{feedback.version if feedback else 0}"
            )
            planned_distance = None
            if match is not None:
                revisions = await uow.workout_revisions.list(user_id, match.planned_workout_id)
                if revisions:
                    planned_distance = revisions[-1].totals.distance_m
            if (
                existing_analysis is not None
                and existing_analysis.normalization_id == selected.normalization.id
                and existing_analysis.analysis_version == analysis_version
                and existing_analysis.planned_workout_id
                == (match.planned_workout_id if match else None)
            ):
                analysis = existing_analysis
            else:
                analysis = analyze_swim(
                    selected,
                    user_id=user_id,
                    analysis_version=analysis_version,
                    planned_workout_id=match.planned_workout_id if match else None,
                    planned_distance_m=planned_distance,
                    feedback=feedback,
                )
                await uow.activity_data.add_analysis(analysis)
                await uow.commit()
        return ActivityDetail(activity, selected, analysis, match, feedback)

    async def get(self, user_id: UserId, activity_id: EntityId) -> ActivityDetail:
        async with self._uow_factory() as uow:
            activity = await uow.activities.get(user_id, activity_id)
            if activity is None:
                raise ResourceNotFoundError("activity")
            normalized = await uow.activity_data.get_current_normalization(user_id, activity_id)
            analysis = await uow.activity_data.get_analysis(user_id, activity_id)
            match = await uow.activity_data.get_match(user_id, activity_id)
            feedback = await uow.activity_data.get_feedback(user_id, activity_id)
        return ActivityDetail(activity, normalized, analysis, match, feedback)

    async def _match_automatically(
        self, user_id: UserId, activity: Activity, normalized: NormalizedActivity
    ) -> WorkoutExecutionMatch | None:
        async with self._uow_factory() as uow:
            existing = await uow.activity_data.get_match(user_id, activity.id)
            if existing is not None and existing.method == "manual":
                return existing
            user = await uow.users.get(user_id)
            workouts = await uow.workouts.list(user_id)
            candidates: list[tuple[Decimal, EntityId, JsonObject]] = []
            try:
                timezone = ZoneInfo(user.timezone if user else "UTC")
            except ZoneInfoNotFoundError:
                timezone = ZoneInfo("UTC")
            activity_date = activity.start_time_utc.astimezone(timezone).date()
            for workout in workouts:
                schedule = await uow.workout_schedules.get(user_id, workout.id)
                revisions = await uow.workout_revisions.list(user_id, workout.id)
                if schedule is None or not revisions:
                    continue
                claimed = await uow.activity_data.get_match_by_workout(user_id, workout.id)
                if claimed is not None and claimed.activity_id != activity.id:
                    continue
                date_gap = abs((schedule.scheduled_date - activity_date).days)
                if date_gap > 1:
                    continue
                revision = revisions[-1]
                estimated_seconds = Decimal(str(revision.totals.estimated_total_seconds))
                distance_max = max(
                    normalized.normalization.distance_m,
                    revision.totals.distance_m,
                    1,
                )
                distance_score = Decimal(1) - Decimal(
                    abs(normalized.normalization.distance_m - revision.totals.distance_m)
                ) / Decimal(distance_max)
                duration_max = max(
                    normalized.normalization.moving_seconds,
                    estimated_seconds,
                    Decimal(1),
                )
                duration_score = (
                    Decimal(1)
                    - abs(normalized.normalization.moving_seconds - estimated_seconds)
                    / duration_max
                )
                date_score = Decimal(1) if date_gap == 0 else Decimal("0.5")
                score = max(
                    Decimal(0),
                    date_score * Decimal("0.45")
                    + max(Decimal(0), distance_score) * Decimal("0.35")
                    + max(Decimal(0), duration_score) * Decimal("0.20"),
                ).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
                candidates.append(
                    (
                        score,
                        workout.id,
                        {
                            "date_score": format(date_score, "f"),
                            "distance_score": format(max(Decimal(0), distance_score), "f"),
                            "duration_score": format(max(Decimal(0), duration_score), "f"),
                        },
                    )
                )
            if not candidates:
                return existing
            score, workout_id, details = max(candidates, key=lambda item: item[0])
            if score < Decimal("0.65"):
                return existing
            match = WorkoutExecutionMatch(
                id=existing.id if existing else EntityId.new(),
                user_id=user_id,
                activity_id=activity.id,
                planned_workout_id=workout_id,
                method="automatic" if score >= Decimal("0.85") else "suggested",
                confidence=score,
                score_details=details,
            )
            await uow.activity_data.upsert_match(match)
            await uow.commit()
            return match

    async def match_manually(
        self,
        user_id: UserId,
        activity_id: EntityId,
        workout_id: EntityId,
        *,
        actor_id: str,
        correlation_id: CorrelationId,
    ) -> WorkoutExecutionMatch:
        async with self._uow_factory() as uow:
            activity = await uow.activities.get(user_id, activity_id)
            workout = await uow.workouts.get(user_id, workout_id)
            if activity is None or workout is None:
                raise ResourceNotFoundError("activity_or_workout")
            existing = await uow.activity_data.get_match(user_id, activity_id)
            claimed = await uow.activity_data.get_match_by_workout(user_id, workout_id)
            if claimed is not None and claimed.activity_id != activity_id:
                raise DomainError(
                    "MATCH_CONFLICT",
                    "The planned workout is already matched to another activity.",
                )
            now = datetime.now(UTC)
            match = WorkoutExecutionMatch(
                id=existing.id if existing else EntityId.new(),
                user_id=user_id,
                activity_id=activity_id,
                planned_workout_id=workout_id,
                method="manual",
                confidence=Decimal(1),
                score_details={"manual_override": True},
                confirmed_at=now,
                confirmed_by=actor_id,
            )
            await uow.activity_data.upsert_match(match)
            await uow.audit.add(
                AuditEvent(
                    id=EntityId.new(),
                    user_id=user_id,
                    actor_type="user",
                    actor_id=actor_id,
                    action="activities.match.corrected",
                    entity_type="activity",
                    entity_id=activity_id,
                    correlation_id=correlation_id,
                    after={"planned_workout_id": str(workout_id), "method": "manual"},
                )
            )
            await uow.commit()
        return match

    async def record_feedback(
        self,
        user_id: UserId,
        activity_id: EntityId,
        *,
        rpe: int,
        technique_rating: int | None,
        fatigue_rating: int | None,
        enjoyment_rating: int | None,
        pain_present: bool,
        pain_location: str | None,
        pain_intensity: int | None,
        comment: str | None,
        expected_version: int | None,
        actor_id: str,
        correlation_id: CorrelationId,
        idempotency_key: str | None = None,
        request_hash: str | None = None,
    ) -> SessionFeedback:
        async with self._uow_factory() as uow:
            activity = await uow.activities.get(user_id, activity_id)
            if activity is None:
                raise ResourceNotFoundError("activity")
            idempotency_scope = f"feedback:{user_id}:{activity_id}"
            if idempotency_key is not None:
                if request_hash is None or len(request_hash) != 64:
                    raise DomainError(
                        "VALIDATION_FAILED", "A request hash is required for idempotency."
                    )
                replay = await uow.idempotency.get(
                    idempotency_scope, idempotency_key, datetime.now(UTC)
                )
                if replay is not None:
                    if replay.request_hash != request_hash:
                        raise DomainError(
                            "IDEMPOTENCY_CONFLICT",
                            "This idempotency key was already used for different feedback.",
                        )
                    existing_feedback = await uow.activity_data.get_feedback(user_id, activity_id)
                    if existing_feedback is None:
                        raise DomainError(
                            "INTERNAL_ERROR", "Idempotent feedback record is inconsistent."
                        )
                    return existing_feedback
            feedback = await uow.activity_data.get_feedback(user_id, activity_id)
            previous_version = feedback.version if feedback else None
            if feedback is None:
                if expected_version is not None:
                    raise DomainError("REVISION_CONFLICT", "Feedback does not exist yet.")
                feedback = SessionFeedback(
                    id=EntityId.new(),
                    user_id=user_id,
                    activity_id=activity_id,
                    rpe=rpe,
                    technique_rating=technique_rating,
                    fatigue_rating=fatigue_rating,
                    enjoyment_rating=enjoyment_rating,
                    pain_present=pain_present,
                    pain_location=pain_location,
                    pain_intensity=pain_intensity,
                    comment=comment,
                )
            else:
                if expected_version != feedback.version:
                    raise DomainError("REVISION_CONFLICT", "Feedback version changed.")
                feedback.revise(
                    rpe=rpe,
                    technique_rating=technique_rating,
                    fatigue_rating=fatigue_rating,
                    enjoyment_rating=enjoyment_rating,
                    pain_present=pain_present,
                    pain_location=pain_location,
                    pain_intensity=pain_intensity,
                    comment=comment,
                )
            await uow.activity_data.upsert_feedback(feedback, expected_version=previous_version)
            normalized = await uow.activity_data.get_current_normalization(user_id, activity_id)
            if normalized is not None:
                match = await uow.activity_data.get_match(user_id, activity_id)
                planned_distance = None
                if match is not None:
                    revisions = await uow.workout_revisions.list(user_id, match.planned_workout_id)
                    if revisions:
                        planned_distance = revisions[-1].totals.distance_m
                await uow.activity_data.add_analysis(
                    analyze_swim(
                        normalized,
                        user_id=user_id,
                        analysis_version=f"{self.ANALYSIS_VERSION}|feedback:{feedback.version}",
                        planned_workout_id=(match.planned_workout_id if match else None),
                        planned_distance_m=planned_distance,
                        feedback=feedback,
                    )
                )
            await uow.audit.add(
                AuditEvent(
                    id=EntityId.new(),
                    user_id=user_id,
                    actor_type="user",
                    actor_id=actor_id,
                    action="feedback.session_recorded",
                    entity_type="activity",
                    entity_id=activity_id,
                    correlation_id=correlation_id,
                    after={
                        "rpe": feedback.rpe,
                        "pain_present": feedback.pain_present,
                        "comment_stored": bool(feedback.comment),
                    },
                )
            )
            if idempotency_key is not None and request_hash is not None:
                now = datetime.now(UTC)
                await uow.idempotency.add(
                    ApiIdempotencyRecord(
                        scope=idempotency_scope,
                        idempotency_key=idempotency_key,
                        request_hash=request_hash,
                        response_status=200,
                        response={"resource_id": str(feedback.id)},
                        created_at=now,
                        expires_at=now + timedelta(hours=24),
                    )
                )
            await uow.commit()
        return feedback
