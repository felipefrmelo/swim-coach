"""FIT artifact ingestion, normalization, analytics, matching and feedback workflows."""

from __future__ import annotations

import hashlib
import io
import logging
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from swim_coach.application.ports.activity_data import FitActivityParser, ObjectStorage
from swim_coach.application.ports.garmin import GarminProvider
from swim_coach.application.ports.repositories import UnitOfWork, UnitOfWorkFactory
from swim_coach.domain.activities import (
    ActivityAnalysis,
    FileArtifact,
    NormalizedActivity,
    SessionFeedback,
    WorkoutExecutionMatch,
    analyze_swim,
)
from swim_coach.domain.activities.contextual import align_planned_steps
from swim_coach.domain.garmin import Activity
from swim_coach.domain.goals import GoalStatus
from swim_coach.domain.operations import ApiIdempotencyRecord, AuditEvent
from swim_coach.domain.shared.errors import DomainError, ResourceNotFoundError
from swim_coach.domain.shared.types import JsonObject
from swim_coach.domain.shared.value_objects import CorrelationId, EntityId, UserId
from swim_coach.domain.workouts import CanonicalWorkout

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ActivityDetail:
    activity: Activity
    normalized: NormalizedActivity | None
    analysis: ActivityAnalysis | None
    match: WorkoutExecutionMatch | None
    feedback: SessionFeedback | None


@dataclass(frozen=True, slots=True)
class _AnalysisContext:
    analysis_version: str
    planned_workout_id: EntityId | None
    planned_distance_m: int | None
    planned_workout: CanonicalWorkout | None
    goal_distance_m: int
    goal_pace_s_per_100m: Decimal


class ActivityDataService:
    ANALYSIS_VERSION = "swim-analysis:2.1.0"
    MAX_FIT_BYTES = 50 * 1024 * 1024

    @staticmethod
    def _fallback_pool_length_m(activity: Activity) -> int | None:
        """Return a corroborated fallback; never reuse an impossible legacy 2000 m pool.

        This value is used only when the FIT itself omits ``session.pool_length`` and
        the parser marks it INFERRED.  A summary value is accepted when it agrees with
        distance/active-length count.  Otherwise the independently reconstructable
        integer value wins; without either evidence, processing fails closed.
        """

        summary_pool = activity.pool_length.meters if activity.pool_length else None
        reconstructed: int | None = None
        if activity.length_count and activity.length_count > 0:
            quotient, remainder = divmod(activity.distance.meters, activity.length_count)
            if remainder == 0 and quotient > 0:
                reconstructed = quotient
        if summary_pool is not None and 0 < summary_pool <= activity.distance.meters:
            if reconstructed is None or abs(summary_pool - reconstructed) <= 1:
                return summary_pool
        if reconstructed is not None:
            return reconstructed
        # Absence is explicit. The parser first inspects session.pool_length and
        # fails closed only when both the FIT fact and this corroborated fallback
        # are unavailable.
        return None

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

    async def _analysis_context(
        self,
        uow: UnitOfWork,
        user_id: UserId,
        match: WorkoutExecutionMatch | None,
        feedback: SessionFeedback | None,
    ) -> _AnalysisContext:
        planned_workout_id = match.planned_workout_id if match is not None else None
        planned_distance_m = None
        planned_workout = None
        workout_context = "none"
        if match is not None:
            workout = await uow.workouts.get(user_id, match.planned_workout_id)
            current_revision_id = workout.current_revision_id if workout is not None else None
            workout_context = (
                f"workout:{match.planned_workout_id}|current:{current_revision_id or 'missing'}"
            )
            if current_revision_id is not None:
                revision = await uow.workout_revisions.get(user_id, current_revision_id)
                if revision is not None and revision.workout_id == match.planned_workout_id:
                    planned_distance_m = revision.totals.distance_m
                    planned_workout = revision.definition
                    workout_context = revision.content_hash

        goals = await uow.goals.list(user_id)
        active_goal = next(
            (item for item in goals if item.status is GoalStatus.ACTIVE),
            None,
        )
        goal_distance_m = active_goal.target_distance.meters if active_goal else 2_000
        goal_pace_s_per_100m = (
            active_goal.target_pace.seconds_per_100m if active_goal else Decimal("135")
        )
        context_hash = hashlib.sha256(
            (
                f"{workout_context}|{goal_distance_m}|{goal_pace_s_per_100m}|"
                f"{active_goal.version if active_goal else 0}"
            ).encode()
        ).hexdigest()[:12]
        feedback_context = "0"
        if feedback is not None:
            feedback_hash = hashlib.sha256(
                f"{feedback.rpe}|{feedback.feeling_score}".encode()
            ).hexdigest()[:8]
            feedback_context = f"{feedback.version}:{feedback_hash}"
        return _AnalysisContext(
            analysis_version=(f"{self.ANALYSIS_VERSION}|fb:{feedback_context}|ctx:{context_hash}"),
            planned_workout_id=planned_workout_id,
            planned_distance_m=planned_distance_m,
            planned_workout=planned_workout,
            goal_distance_m=goal_distance_m,
            goal_pace_s_per_100m=goal_pace_s_per_100m,
        )

    @staticmethod
    def _analyze(
        normalized: NormalizedActivity,
        user_id: UserId,
        context: _AnalysisContext,
        feedback: SessionFeedback | None,
    ) -> ActivityAnalysis:
        return analyze_swim(
            normalized,
            user_id=user_id,
            analysis_version=context.analysis_version,
            planned_workout_id=context.planned_workout_id,
            planned_distance_m=context.planned_distance_m,
            planned_workout=context.planned_workout,
            goal_distance_m=context.goal_distance_m,
            goal_pace_s_per_100m=context.goal_pace_s_per_100m,
            feedback=feedback,
        )

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
                candidate = FileArtifact(
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
                artifact = await uow.activity_data.add_artifact(candidate)
                await uow.commit()
        return await self._normalize_artifact(activity, artifact, fit_data)

    async def process_local(self, user_id: UserId, activity_id: EntityId) -> ActivityDetail:
        """Reprocess the newest immutable local FIT without contacting Garmin."""

        async with self._uow_factory() as uow:
            activity = await uow.activities.get(user_id, activity_id)
            artifacts = await uow.activity_data.list_artifacts(user_id)
        if activity is None:
            raise ResourceNotFoundError("activity")
        candidates = [
            item
            for item in artifacts
            if item.activity_id == activity_id and item.artifact_type == "fit"
        ]
        if not candidates:
            raise DomainError(
                "FIT_FILE_UNAVAILABLE",
                "No local FIT artifact is available; Garmin was not contacted.",
            )
        artifact = max(candidates, key=lambda item: item.created_at)
        fit_data = await self._storage.get(artifact.storage_key)
        if hashlib.sha256(fit_data).hexdigest() != artifact.checksum:
            raise DomainError(
                "ARTIFACT_CHECKSUM_MISMATCH", "Stored FIT checksum did not match metadata."
            )
        return await self._normalize_artifact(activity, artifact, fit_data)

    async def _normalize_artifact(
        self, activity: Activity, artifact: FileArtifact, fit_data: bytes
    ) -> ActivityDetail:
        user_id = activity.user_id
        checksum = artifact.checksum
        pool_length_m = self._fallback_pool_length_m(activity)
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
            await uow.commit()
        normalization = selected.normalization
        LOGGER.info(
            "activity_normalized",
            extra={
                "activity_id": str(activity.id),
                "garmin_activity_id_hash": hashlib.sha256(
                    activity.external_activity_id.encode()
                ).hexdigest(),
                "summary_pool_length_m": (
                    activity.pool_length.meters if activity.pool_length else None
                ),
                "normalized_pool_length_m": normalization.pool_length_m,
                "distance_m": normalization.distance_m,
                "elapsed_duration_s": format(normalization.elapsed_seconds, "f"),
                "timer_duration_s": format(normalization.timer_seconds, "f"),
                "moving_duration_s": (
                    format(normalization.moving_seconds, "f")
                    if normalization.moving_seconds is not None
                    else None
                ),
                "interval_count": len(selected.intervals),
                "length_count": len(selected.lengths),
                "parser_version": normalization.parser_version,
                "garmin_rpe_present": normalization.perceived_effort_rpe is not None,
                "garmin_feeling_present": normalization.feeling_score is not None,
                "normalization_warnings": list(normalization.warnings),
            },
        )
        async with self._uow_factory() as uow:
            match = await self._match_automatically(uow, user_id, activity, selected)
            feedback = await uow.activity_data.get_feedback(user_id, activity.id)
            context = await self._analysis_context(uow, user_id, match, feedback)
            existing_analysis = await uow.activity_data.get_analysis_by_context(
                user_id,
                activity.id,
                selected.normalization.id,
                context.analysis_version,
                context.planned_workout_id,
            )
            analysis_reused = existing_analysis is not None
            if existing_analysis is not None:
                analysis = existing_analysis
            else:
                analysis = await uow.activity_data.add_analysis(
                    self._analyze(selected, user_id, context, feedback)
                )
            if match is not None:
                await uow.activity_data.upsert_match(match)
            # The canonical pointer and its matching analysis become visible
            # atomically. A failed analysis leaves the prior normalization
            # active while retaining the immutable candidate for safe retry.
            await uow.activity_data.promote_normalization(
                user_id,
                activity.id,
                selected.normalization.id,
                analysis.id,
            )
            await uow.commit()
        raw_sets = analysis.metrics.get("sets")
        LOGGER.info(
            "activity_analyzed",
            extra={
                "activity_id": str(activity.id),
                "garmin_activity_id_hash": hashlib.sha256(
                    activity.external_activity_id.encode()
                ).hexdigest(),
                "normalization_id": str(selected.normalization.id),
                "parser_version": selected.normalization.parser_version,
                "analysis_version": analysis.analysis_version,
                "analysis_reused": analysis_reused,
                "analysis_quality": analysis.quality.value,
                "analysis_warning_count": len(analysis.flags),
                "equivalent_set_count": len(raw_sets) if isinstance(raw_sets, list) else 0,
                "planned_workout_matched": match is not None,
            },
        )
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
        self,
        uow: UnitOfWork,
        user_id: UserId,
        activity: Activity,
        normalized: NormalizedActivity,
    ) -> WorkoutExecutionMatch | None:
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
            if schedule is None or workout.current_revision_id is None:
                continue
            revision = await uow.workout_revisions.get(user_id, workout.current_revision_id)
            if revision is None or revision.workout_id != workout.id:
                continue
            claimed = await uow.activity_data.get_match_by_workout(user_id, workout.id)
            if claimed is not None and claimed.activity_id != activity.id:
                continue
            date_gap = abs((schedule.scheduled_date - activity_date).days)
            if date_gap > 1:
                continue
            estimated_seconds = Decimal(str(revision.totals.estimated_total_seconds))
            distance_max = max(
                normalized.normalization.distance_m,
                revision.totals.distance_m,
                1,
            )
            distance_score = Decimal(1) - Decimal(
                abs(normalized.normalization.distance_m - revision.totals.distance_m)
            ) / Decimal(distance_max)
            # Planned estimated_total_seconds includes explicit rests, so timer
            # duration is the only like-for-like canonical activity basis.
            comparable_duration = normalized.normalization.timer_seconds
            duration_max = max(comparable_duration, estimated_seconds, Decimal(1))
            duration_score = (
                Decimal(1) - abs(comparable_duration - estimated_seconds) / duration_max
            )
            adherence = align_planned_steps(
                revision.definition,
                normalized.intervals,
                pace_basis="best_available",
            )
            step_score = (adherence.matched_step_ratio or Decimal(0)) * Decimal("0.60") + (
                adherence.mean_alignment_confidence or Decimal(0)
            ) * Decimal("0.40")
            date_score = Decimal(1) if date_gap == 0 else Decimal("0.5")
            score = max(
                Decimal(0),
                date_score * Decimal("0.35")
                + max(Decimal(0), distance_score) * Decimal("0.25")
                + max(Decimal(0), duration_score) * Decimal("0.15")
                + max(Decimal(0), step_score) * Decimal("0.25"),
            ).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
            candidates.append(
                (
                    score,
                    workout.id,
                    {
                        "date_score": format(date_score, "f"),
                        "distance_score": format(max(Decimal(0), distance_score), "f"),
                        "duration_score": format(max(Decimal(0), duration_score), "f"),
                        "duration_basis": "timer_duration_s",
                        "step_alignment_score": format(max(Decimal(0), step_score), "f"),
                        "matched_step_ratio": (
                            format(adherence.matched_step_ratio, "f")
                            if adherence.matched_step_ratio is not None
                            else None
                        ),
                        "alignment_quality": adherence.quality.level.value,
                    },
                )
            )
        if not candidates:
            return existing
        score, workout_id, details = max(candidates, key=lambda item: item[0])
        if score < Decimal("0.65"):
            return existing
        return WorkoutExecutionMatch(
            id=existing.id if existing else EntityId.new(),
            user_id=user_id,
            activity_id=activity.id,
            planned_workout_id=workout_id,
            method="automatic" if score >= Decimal("0.85") else "suggested",
            confidence=score,
            score_details=details,
        )

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
            normalized = await uow.activity_data.get_current_normalization(user_id, activity_id)
            if normalized is not None:
                feedback = await uow.activity_data.get_feedback(user_id, activity_id)
                context = await self._analysis_context(uow, user_id, match, feedback)
                analysis = await uow.activity_data.get_analysis_by_context(
                    user_id,
                    activity_id,
                    normalized.normalization.id,
                    context.analysis_version,
                    context.planned_workout_id,
                )
                if analysis is None:
                    analysis = await uow.activity_data.add_analysis(
                        self._analyze(normalized, user_id, context, feedback)
                    )
                await uow.activity_data.promote_normalization(
                    user_id,
                    activity_id,
                    normalized.normalization.id,
                    analysis.id,
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
        rpe: int | None,
        technique_rating: int | None,
        fatigue_rating: int | None,
        enjoyment_rating: int | None,
        feeling_score: int | None = None,
        pain_present: bool,
        pain_location: str | None,
        pain_intensity: int | None,
        comment: str | None,
        expected_version: int | None,
        actor_id: str,
        correlation_id: CorrelationId,
        idempotency_key: str | None = None,
        request_hash: str | None = None,
        reuse_idempotency_key_when_state_changed: bool = False,
        preserve_existing_feeling_score: bool = False,
    ) -> SessionFeedback | None:
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
                await uow.idempotency.lock(idempotency_scope, idempotency_key)
                idempotency_now = datetime.now(UTC)
                replay = await uow.idempotency.get(
                    idempotency_scope, idempotency_key, idempotency_now
                )
                if replay is not None:
                    if replay.request_hash != request_hash:
                        raise DomainError(
                            "IDEMPOTENCY_CONFLICT",
                            "This idempotency key was already used for different feedback.",
                        )
                    existing_feedback = await uow.activity_data.get_feedback(user_id, activity_id)
                    replay_cleared = replay.response.get("cleared") is True
                    replay_resource_id = replay.response.get("resource_id")
                    replay_version = replay.response.get("version")
                    replay_matches_state = (
                        existing_feedback is None
                        if replay_cleared
                        else existing_feedback is not None
                        and replay_resource_id == str(existing_feedback.id)
                        and (replay_version is None or replay_version == existing_feedback.version)
                    )
                    if not replay_matches_state:
                        if reuse_idempotency_key_when_state_changed:
                            await uow.idempotency.delete(idempotency_scope, idempotency_key)
                        else:
                            raise DomainError(
                                "IDEMPOTENCY_CONFLICT",
                                "The stored feedback replay no longer matches current state.",
                            )
                    elif replay_cleared:
                        return None
                    elif existing_feedback is not None:
                        return existing_feedback
                    else:  # pragma: no cover - replay_matches_state makes this unreachable
                        raise DomainError(
                            "INTERNAL_ERROR", "Idempotent feedback record is inconsistent."
                        )
                else:
                    # The advisory lock makes it safe to remove an expired row before
                    # the eventual insert without racing another first request.
                    await uow.idempotency.delete(idempotency_scope, idempotency_key)
            feedback = await uow.activity_data.get_feedback(user_id, activity_id)
            normalized = await uow.activity_data.get_current_normalization(user_id, activity_id)
            stored_feeling_score = (
                feedback.feeling_score
                if preserve_existing_feeling_score and feedback is not None
                else feeling_score
            )
            clear_manual_feedback = (
                rpe is None
                and technique_rating is None
                and fatigue_rating is None
                and enjoyment_rating is None
                and stored_feeling_score is None
                and not pain_present
                and pain_location is None
                and pain_intensity is None
                and not (comment and comment.strip())
            )
            if clear_manual_feedback and feedback is None:
                raise DomainError(
                    "VALIDATION_FAILED",
                    "At least one manual feedback field is required.",
                )
            if (
                not clear_manual_feedback
                and rpe is None
                and (normalized is None or normalized.normalization.perceived_effort_rpe is None)
            ):
                raise DomainError(
                    "VALIDATION_FAILED",
                    "RPE is required when the normalized Garmin activity has no perceived effort.",
                )
            previous_version = feedback.version if feedback else None
            stored_feedback: SessionFeedback | None
            if clear_manual_feedback:
                if feedback is None:
                    raise DomainError("INTERNAL_ERROR", "Feedback clear state became inconsistent.")
                if expected_version is not None and expected_version != feedback.version:
                    raise DomainError("REVISION_CONFLICT", "Feedback version changed.")
                await uow.activity_data.delete_feedback(
                    user_id,
                    activity_id,
                    expected_version=feedback.version,
                )
                stored_feedback = None
            elif feedback is None:
                if expected_version is not None:
                    raise DomainError("REVISION_CONFLICT", "Feedback does not exist yet.")
                stored_feedback = SessionFeedback(
                    id=EntityId.new(),
                    user_id=user_id,
                    activity_id=activity_id,
                    rpe=rpe,
                    provider=activity.provider,
                    external_activity_id=activity.external_activity_id,
                    technique_rating=technique_rating,
                    fatigue_rating=fatigue_rating,
                    enjoyment_rating=enjoyment_rating,
                    feeling_score=stored_feeling_score,
                    pain_present=pain_present,
                    pain_location=pain_location,
                    pain_intensity=pain_intensity,
                    comment=comment,
                )
            else:
                if expected_version is not None and expected_version != feedback.version:
                    raise DomainError("REVISION_CONFLICT", "Feedback version changed.")
                feedback.revise(
                    rpe=rpe,
                    technique_rating=technique_rating,
                    fatigue_rating=fatigue_rating,
                    enjoyment_rating=enjoyment_rating,
                    feeling_score=stored_feeling_score,
                    pain_present=pain_present,
                    pain_location=pain_location,
                    pain_intensity=pain_intensity,
                    comment=comment,
                )
                stored_feedback = feedback
            if stored_feedback is not None:
                await uow.activity_data.upsert_feedback(
                    stored_feedback, expected_version=previous_version
                )
            if normalized is not None:
                match = await uow.activity_data.get_match(user_id, activity_id)
                context = await self._analysis_context(uow, user_id, match, stored_feedback)
                analysis = await uow.activity_data.add_analysis(
                    self._analyze(normalized, user_id, context, stored_feedback)
                )
                await uow.activity_data.promote_normalization(
                    user_id,
                    activity_id,
                    normalized.normalization.id,
                    analysis.id,
                )
            await uow.audit.add(
                AuditEvent(
                    id=EntityId.new(),
                    user_id=user_id,
                    actor_type="user",
                    actor_id=actor_id,
                    action=(
                        "feedback.session_cleared"
                        if stored_feedback is None
                        else "feedback.session_recorded"
                    ),
                    entity_type="activity",
                    entity_id=activity_id,
                    correlation_id=correlation_id,
                    after={
                        "rpe_override": (
                            stored_feedback.rpe is not None
                            if stored_feedback is not None
                            else False
                        ),
                        "feeling_score_override": (
                            stored_feedback.feeling_score is not None
                            if stored_feedback is not None
                            else False
                        ),
                        "pain_present": (
                            stored_feedback.pain_present if stored_feedback is not None else False
                        ),
                        "comment_stored": bool(
                            stored_feedback.comment if stored_feedback is not None else None
                        ),
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
                        response={
                            "resource_id": (
                                str(stored_feedback.id) if stored_feedback is not None else None
                            ),
                            "cleared": stored_feedback is None,
                            "version": (
                                stored_feedback.version if stored_feedback is not None else None
                            ),
                        },
                        created_at=now,
                        expires_at=now + timedelta(hours=24),
                    )
                )
            await uow.commit()
        return stored_feedback
