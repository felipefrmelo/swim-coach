"""SQLAlchemy repositories and unit-of-work adapter."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, timedelta
from decimal import Decimal
from types import TracebackType
from typing import Any, Self, cast

from sqlalchemy import and_, delete, exists, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from swim_coach.application.ports.repositories import UnitOfWork
from swim_coach.domain.actions import (
    ActionApproval,
    ActionExecution,
    ActionExecutionStatus,
    ActionProposal,
    ActionProposalStatus,
    ExternalWorkoutBinding,
    ExternalWorkoutBindingStatus,
)
from swim_coach.domain.activities import (
    ActivityAnalysis,
    ActivityInterval,
    ActivityLap,
    ActivityLength,
    ActivityNormalization,
    DataQuality,
    FileArtifact,
    NormalizedActivity,
    SessionFeedback,
    WorkoutExecutionMatch,
)
from swim_coach.domain.athlete import (
    AthleteConstraint,
    AthleteProfile,
    AvailabilityRule,
    ConstraintType,
    Device,
    Pool,
)
from swim_coach.domain.garmin import (
    Activity,
    ActivityImport,
    ActivityImportStatus,
    GarminConnection,
    GarminConnectionStatus,
    RawProviderPayload,
    SyncCursor,
    SyncRun,
    SyncRunStatus,
)
from swim_coach.domain.goals import GoalMilestone, GoalStatus, TrainingGoal
from swim_coach.domain.identity import (
    AppUser,
    AuthIdentity,
    OidcLoginAttempt,
    UserStatus,
    WebSession,
)
from swim_coach.domain.operations import (
    ApiIdempotencyRecord,
    AuditEvent,
    DataExport,
    DataExportStatus,
    DeletionRequest,
    DeletionRequestStatus,
    Job,
    JobStatus,
    McpToolInvocation,
    Notification,
    OutboxEvent,
)
from swim_coach.domain.planning import (
    PlanningRules,
    PlanningRun,
    PlanningRunStatus,
    TrainingDecisionRecord,
    TrainingRuleSet,
)
from swim_coach.domain.shared.errors import RevisionConflictError
from swim_coach.domain.shared.types import JsonObject
from swim_coach.domain.shared.value_objects import (
    Distance,
    Duration,
    EncryptedSecret,
    EntityId,
    Pace,
    PoolLength,
    UserId,
)
from swim_coach.domain.workouts import (
    CanonicalWorkout,
    PlannedWorkout,
    PlannedWorkoutStatus,
    WorkoutRevision,
    WorkoutSchedule,
    WorkoutTemplate,
    WorkoutTotals,
)
from swim_coach.infrastructure.db.models import (
    ActionApprovalModel,
    ActionExecutionModel,
    ActionProposalModel,
    ActivityAnalysisModel,
    ActivityImportModel,
    ActivityIntervalModel,
    ActivityLapModel,
    ActivityLengthModel,
    ActivityModel,
    ActivityNormalizationModel,
    ApiIdempotencyRecordModel,
    AppUserModel,
    AthleteConstraintModel,
    AthleteProfileModel,
    AuditEventModel,
    AuthIdentityModel,
    AvailabilityRuleModel,
    DataExportModel,
    DeletionRequestModel,
    DeviceModel,
    ExternalWorkoutBindingModel,
    FileArtifactModel,
    GarminConnectionModel,
    GoalMilestoneModel,
    JobModel,
    McpToolInvocationModel,
    NotificationModel,
    OidcLoginAttemptModel,
    OutboxEventModel,
    PlannedWorkoutModel,
    PlanningRunModel,
    PoolModel,
    RawProviderPayloadModel,
    SessionFeedbackModel,
    SyncCursorModel,
    SyncRunModel,
    TrainingDecisionModel,
    TrainingGoalModel,
    TrainingRuleSetModel,
    WebSessionModel,
    WorkoutExecutionMatchModel,
    WorkoutRevisionModel,
    WorkoutScheduleModel,
    WorkoutTemplateModel,
)


def _json(value: dict[str, Any]) -> JsonObject:
    return cast(JsonObject, value)


def _optional_decimal(value: Decimal | None) -> Decimal | None:
    return Decimal(value) if value is not None else None


_LEGACY_V1_MOVING_WARNING = "LEGACY_V1_MOVING_DURATION_INVALIDATED"
_LEGACY_V1_CHILD_WARNING = "LEGACY_V1_CANONICAL_FIELDS_UNAVAILABLE"


def _is_legacy_v1_parser(parser_version: str) -> bool:
    return "|swim-coach:1." in parser_version


def _with_warning(values: Sequence[str], warning: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys((*values, warning)))


def _legacy_child_provenance(value: dict[str, Any], *, legacy_v1: bool) -> JsonObject:
    result = dict(value)
    if legacy_v1:
        result.setdefault(
            "canonical_v2",
            {
                "source": "inferred",
                "interpretation": "legacy_v1_fields_unavailable",
            },
        )
    return _json(result)


def _user(model: AppUserModel) -> AppUser:
    return AppUser(
        id=UserId(model.id),
        email=model.email,
        display_name=model.display_name,
        locale=model.locale,
        timezone=model.timezone,
        status=UserStatus(model.status),
        last_login_at=model.last_login_at,
        created_at=model.created_at,
        updated_at=model.updated_at,
        version=model.version,
    )


def _profile(model: AthleteProfileModel) -> AthleteProfile:
    return AthleteProfile(
        user_id=UserId(model.user_id),
        experience_level=model.experience_level,
        preferred_distance_unit=model.preferred_distance_unit,
        default_pool_id=EntityId(model.default_pool_id) if model.default_pool_id else None,
        default_sessions_per_week=model.default_sessions_per_week,
        goal_notes=model.goal_notes,
        coach_preferences=_json(model.coach_preferences_json),
        created_at=model.created_at,
        updated_at=model.updated_at,
        version=model.version,
    )


def _pool(model: PoolModel) -> Pool:
    return Pool(
        id=EntityId(model.id),
        user_id=UserId(model.user_id),
        name=model.name,
        length=PoolLength(model.length_m),
        is_default=model.is_default,
        location_label=model.location_label,
        active=model.active,
        created_at=model.created_at,
        updated_at=model.updated_at,
        version=model.version,
    )


def _availability(model: AvailabilityRuleModel) -> AvailabilityRule:
    return AvailabilityRule(
        id=EntityId(model.id),
        user_id=UserId(model.user_id),
        day_of_week=model.day_of_week,
        start_local_time=model.start_local_time,
        end_local_time=model.end_local_time,
        max_duration_minutes=model.max_duration_minutes,
        pool_id=EntityId(model.pool_id) if model.pool_id else None,
        valid_from=model.valid_from,
        valid_until=model.valid_until,
        priority=model.priority,
        created_at=model.created_at,
        updated_at=model.updated_at,
        version=model.version,
    )


def _constraint(model: AthleteConstraintModel) -> AthleteConstraint:
    return AthleteConstraint(
        id=EntityId(model.id),
        user_id=UserId(model.user_id),
        constraint_type=ConstraintType(model.type),
        severity=model.severity,
        active_from=model.active_from,
        active_until=model.active_until,
        notes=model.notes,
        is_active=model.is_active,
        created_at=model.created_at,
        updated_at=model.updated_at,
        version=model.version,
    )


def _device(model: DeviceModel) -> Device:
    return Device(
        id=EntityId(model.id),
        user_id=UserId(model.user_id),
        provider=model.provider,
        external_device_id=model.external_device_id,
        model=model.model,
        name=model.name,
        serial_hash=model.serial_hash,
        is_primary=model.is_primary,
        capabilities=_json(model.capabilities_json),
        last_seen_at=model.last_seen_at,
        created_at=model.created_at,
        updated_at=model.updated_at,
        version=model.version,
    )


def _goal(model: TrainingGoalModel) -> TrainingGoal:
    goal = TrainingGoal(
        id=EntityId(model.id),
        user_id=UserId(model.user_id),
        goal_type=model.type,
        title=model.title,
        status=GoalStatus(model.status),
        priority=model.priority,
        target_distance=Distance(model.target_distance_m),
        target_duration=Duration(Decimal(model.target_duration_seconds)),
        target_date=model.target_date,
        baseline=_json(model.baseline_json),
        metadata=_json(model.metadata_json),
        created_at=model.created_at,
        updated_at=model.updated_at,
        completed_at=model.completed_at,
        version=model.version,
    )
    goal.target_pace = Pace(Decimal(model.target_pace_seconds_per_100m))
    return goal


def _workout(model: PlannedWorkoutModel) -> PlannedWorkout:
    return PlannedWorkout(
        id=EntityId(model.id),
        user_id=UserId(model.user_id),
        title=model.title,
        purpose=model.purpose,
        pool_id=EntityId(model.pool_id),
        status=PlannedWorkoutStatus(model.status),
        current_revision_id=EntityId(model.current_revision_id)
        if model.current_revision_id
        else None,
        approved_revision_id=EntityId(model.approved_revision_id)
        if model.approved_revision_id
        else None,
        source=model.source,
        created_at=model.created_at,
        updated_at=model.updated_at,
        version=model.version,
    )


def _workout_revision(model: WorkoutRevisionModel) -> WorkoutRevision:
    totals = WorkoutTotals(
        distance_m=model.total_distance_m,
        distance_steps=model.distance_steps,
        executable_steps=model.executable_steps,
        lengths=model.lengths,
        active_seconds=float(model.estimated_active_seconds),
        rest_seconds=float(model.estimated_rest_seconds),
        estimated_total_seconds=float(model.estimated_total_seconds),
    )
    return WorkoutRevision(
        id=EntityId(model.id),
        workout_id=EntityId(model.workout_id),
        revision_number=model.revision_number,
        definition=CanonicalWorkout.model_validate(model.definition_json),
        totals=totals,
        validation=dict(model.validation_json),
        content_hash=model.content_hash,
        change_reason=model.change_reason,
        created_by_type=model.created_by_type,
        created_by_id=model.created_by_id,
        created_at=model.created_at,
    )


def _workout_schedule(model: WorkoutScheduleModel) -> WorkoutSchedule:
    return WorkoutSchedule(
        id=EntityId(model.id),
        workout_id=EntityId(model.workout_id),
        scheduled_date=model.scheduled_date,
        scheduled_start_time=model.scheduled_start_time,
        timezone=model.timezone,
        pool_id=EntityId(model.pool_id),
        created_at=model.created_at,
    )


def _analysis(model: ActivityAnalysisModel) -> ActivityAnalysis:
    return ActivityAnalysis(
        id=EntityId(model.id),
        user_id=UserId(model.user_id),
        activity_id=EntityId(model.activity_id),
        normalization_id=EntityId(model.normalization_id),
        analysis_version=model.analysis_version,
        parser_version=model.parser_version,
        input_checksum=model.input_checksum,
        pool_length_m=model.pool_length_m,
        metrics=_json(model.metrics_json),
        flags=tuple(model.flags_json),
        quality=DataQuality(model.quality),
        summary=_json(model.summary_json),
        planned_workout_id=(
            EntityId(model.planned_workout_id) if model.planned_workout_id else None
        ),
        created_at=model.created_at,
    )


def _job(model: JobModel) -> Job:
    return Job(
        id=EntityId(model.id),
        user_id=UserId(model.user_id) if model.user_id else None,
        job_type=model.job_type,
        payload=_json(model.payload_json),
        status=JobStatus(model.status),
        priority=model.priority,
        available_at=model.available_at,
        attempts=model.attempts,
        max_attempts=model.max_attempts,
        idempotency_key=model.idempotency_key,
        locked_by=model.locked_by,
        locked_at=model.locked_at,
        heartbeat_at=model.heartbeat_at,
        lease_expires_at=model.lease_expires_at,
        last_error=_json(model.last_error_json_redacted)
        if model.last_error_json_redacted
        else None,
        created_at=model.created_at,
        updated_at=model.updated_at,
        finished_at=model.finished_at,
        version=model.version,
    )


def _file_artifact(model: FileArtifactModel) -> FileArtifact:
    return FileArtifact(
        id=EntityId(model.id),
        user_id=UserId(model.user_id),
        activity_id=EntityId(model.activity_id),
        provider=model.provider,
        artifact_type=model.artifact_type,
        storage_key=model.storage_key,
        content_type=model.content_type,
        size_bytes=model.size_bytes,
        checksum=model.checksum,
        source_external_id_hash=model.source_external_id_hash,
        created_at=model.created_at,
    )


def _data_export(model: DataExportModel) -> DataExport:
    return DataExport(
        id=EntityId(model.id),
        user_id=UserId(model.user_id),
        status=DataExportStatus(model.status),
        storage_key=model.storage_key,
        checksum=model.checksum,
        size_bytes=model.size_bytes,
        created_at=model.created_at,
        completed_at=model.completed_at,
        expires_at=model.expires_at,
    )


def _deletion_request(model: DeletionRequestModel) -> DeletionRequest:
    return DeletionRequest(
        id=EntityId(model.id),
        user_id=UserId(model.user_id) if model.user_id else None,
        status=DeletionRequestStatus(model.status),
        execute_after=model.execute_after,
        created_at=model.created_at,
        executed_at=model.executed_at,
    )


def _notification(model: NotificationModel) -> Notification:
    return Notification(
        id=EntityId(model.id),
        user_id=UserId(model.user_id),
        notification_type=model.notification_type,
        dedupe_key=model.dedupe_key,
        title=model.title,
        body=model.body,
        link=model.link,
        read_at=model.read_at,
        created_at=model.created_at,
    )


def _action_proposal(model: ActionProposalModel) -> ActionProposal:
    return ActionProposal(
        id=EntityId(model.id),
        user_id=UserId(model.user_id),
        action_type=model.action_type,
        target_type=model.target_type,
        target_id=EntityId(model.target_id),
        target_revision_id=(
            EntityId(model.target_revision_id) if model.target_revision_id else None
        ),
        payload=_json(model.payload_json),
        impact=_json(model.impact_json),
        action_hash=model.action_hash,
        expires_at=model.expires_at,
        status=ActionProposalStatus(model.status),
        created_at=model.created_at,
        updated_at=model.updated_at,
        version=model.version,
    )


def _action_execution(model: ActionExecutionModel) -> ActionExecution:
    return ActionExecution(
        id=EntityId(model.id),
        proposal_id=EntityId(model.proposal_id),
        user_id=UserId(model.user_id),
        idempotency_key=model.idempotency_key,
        status=ActionExecutionStatus(model.status),
        result=_json(model.result_json) if model.result_json else None,
        error=_json(model.error_json_redacted) if model.error_json_redacted else None,
        started_at=model.started_at,
        finished_at=model.finished_at,
        created_at=model.created_at,
        updated_at=model.updated_at,
        version=model.version,
    )


def _training_rule_set(model: TrainingRuleSetModel) -> TrainingRuleSet:
    return TrainingRuleSet(
        id=EntityId(model.id),
        name=model.name,
        version=model.version,
        rules=PlanningRules.model_validate(model.rules_json),
        content_hash=model.content_hash,
        effective_from=model.effective_from,
        effective_until=model.effective_until,
        schema_version=model.schema_version,
        created_at=model.created_at,
    )


def _planning_run(model: PlanningRunModel) -> PlanningRun:
    return PlanningRun(
        id=EntityId(model.id),
        user_id=UserId(model.user_id),
        goal_id=EntityId(model.goal_id),
        rule_set_id=EntityId(model.rule_set_id),
        week_start=model.week_start,
        input_snapshot=_json(model.input_snapshot_json),
        input_hash=model.input_hash,
        output_plan=_json(model.output_plan_json),
        output_proposal_id=(
            EntityId(model.output_proposal_id) if model.output_proposal_id else None
        ),
        status=PlanningRunStatus(model.status),
        warnings=tuple(model.warnings_json),
        created_at=model.created_at,
        completed_at=model.completed_at,
    )


def _training_decision(model: TrainingDecisionModel) -> TrainingDecisionRecord:
    return TrainingDecisionRecord(
        id=EntityId(model.id),
        user_id=UserId(model.user_id),
        planning_run_id=EntityId(model.planning_run_id),
        order_index=model.order_index,
        decision_type=model.decision_type,
        rule_id=model.rule_id,
        effective_date=model.effective_date,
        evidence_refs=tuple(model.evidence_refs_json),
        before=_json(model.before_json),
        after=_json(model.after_json),
        rationale=model.rationale,
        actor_type=model.actor_type,
        actor_id=model.actor_id,
        created_at=model.created_at,
    )


def _external_workout_binding(model: ExternalWorkoutBindingModel) -> ExternalWorkoutBinding:
    return ExternalWorkoutBinding(
        id=EntityId(model.id),
        user_id=UserId(model.user_id),
        workout_id=EntityId(model.workout_id),
        revision_id=EntityId(model.revision_id),
        provider=model.provider,
        compiled_hash=model.compiled_hash,
        status=ExternalWorkoutBindingStatus(model.status),
        external_workout_id=model.external_workout_id,
        external_schedule_id=model.external_schedule_id,
        scheduled_date=model.scheduled_date,
        last_error=(
            _json(model.last_error_json_redacted) if model.last_error_json_redacted else None
        ),
        created_at=model.created_at,
        updated_at=model.updated_at,
        version=model.version,
    )


def _garmin_connection(model: GarminConnectionModel) -> GarminConnection:
    secret = None
    if model.encrypted_token_bundle is not None:
        secret = EncryptedSecret(
            ciphertext=model.encrypted_token_bundle,
            nonce=cast(bytes, model.token_nonce),
            key_version=cast(str, model.token_key_version),
        )
    return GarminConnection(
        user_id=UserId(model.user_id),
        status=GarminConnectionStatus(model.status),
        account_label_masked=model.account_label_masked,
        encrypted_token=secret,
        provider_library_version=model.provider_library_version,
        authenticated_at=model.authenticated_at,
        last_refresh_at=model.last_refresh_at,
        last_success_at=model.last_success_at,
        last_error_code=model.last_error_code,
        last_error_message_redacted=model.last_error_message_redacted,
        created_at=model.created_at,
        updated_at=model.updated_at,
        version=model.version,
    )


def _sync_cursor(model: SyncCursorModel) -> SyncCursor:
    return SyncCursor(
        id=EntityId(model.id),
        user_id=UserId(model.user_id),
        provider=model.provider,
        entity_type=model.entity_type,
        cursor=_json(model.cursor_json),
        watermark_at=model.watermark_at,
        last_success_at=model.last_success_at,
        overlap_seconds=model.overlap_seconds,
        created_at=model.created_at,
        updated_at=model.updated_at,
        version=model.version,
    )


def _sync_run(model: SyncRunModel) -> SyncRun:
    return SyncRun(
        id=EntityId(model.id),
        user_id=UserId(model.user_id),
        provider=model.provider,
        sync_type=model.sync_type,
        trigger=model.trigger,
        status=SyncRunStatus(model.status),
        listed=model.listed,
        created=model.created,
        updated=model.updated,
        skipped=model.skipped,
        failed=model.failed,
        cursor_before=_json(model.cursor_before_json),
        cursor_after=_json(model.cursor_after_json),
        error=_json(model.error_json_redacted) if model.error_json_redacted else None,
        started_at=model.started_at,
        finished_at=model.finished_at,
        version=model.version,
    )


def _activity(model: ActivityModel) -> Activity:
    return Activity(
        id=EntityId(model.id),
        user_id=UserId(model.user_id),
        provider=model.provider,
        external_activity_id=model.external_activity_id,
        name=model.name,
        sport=model.sport,
        subtype=model.subtype,
        start_time_utc=model.start_time_utc,
        timezone=model.timezone,
        distance=Distance(model.distance_m),
        elapsed=Duration(Decimal(model.elapsed_seconds)),
        timer=Duration(Decimal(model.timer_seconds)),
        moving=Duration(Decimal(model.moving_seconds)),
        pool_length=PoolLength(model.pool_length_m) if model.pool_length_m else None,
        length_count=model.length_count,
        calories=model.calories,
        avg_hr=model.avg_hr,
        max_hr=model.max_hr,
        avg_pace_seconds_per_100m=model.avg_pace_seconds_per_100m,
        avg_stroke_rate=model.avg_stroke_rate,
        avg_strokes_per_length=model.avg_strokes_per_length,
        avg_swolf=model.avg_swolf,
        source_updated_at=model.source_updated_at,
        normalization_version=model.normalization_version,
        raw_summary_id=EntityId(model.raw_summary_id),
        raw_fit_id=EntityId(model.raw_fit_id) if model.raw_fit_id else None,
        summary_checksum=model.summary_checksum,
        created_at=model.created_at,
        updated_at=model.updated_at,
        version=model.version,
    )


def _raw_provider_payload(model: RawProviderPayloadModel) -> RawProviderPayload:
    return RawProviderPayload(
        id=EntityId(model.id),
        user_id=UserId(model.user_id),
        provider=model.provider,
        entity_type=model.entity_type,
        external_id=model.external_id,
        content_type=model.content_type,
        payload=_json(model.json_payload),
        checksum=model.checksum,
        provider_updated_at=model.provider_updated_at,
        received_at=model.received_at,
    )


def _normalization(model: ActivityNormalizationModel) -> ActivityNormalization:
    legacy_v1 = _is_legacy_v1_parser(model.parser_version)
    warnings = tuple(model.warnings_json)
    provenance = dict(model.provenance_json)
    if legacy_v1:
        warnings = _with_warning(warnings, _LEGACY_V1_MOVING_WARNING)
        provenance["moving_seconds"] = {
            "source": "inferred",
            "interpretation": "legacy_v1_timer_alias_invalidated",
            "transformation": "known parser-v1 timer fallback exposed as unavailable",
        }
    return ActivityNormalization(
        id=EntityId(model.id),
        user_id=UserId(model.user_id),
        activity_id=EntityId(model.activity_id),
        artifact_id=EntityId(model.artifact_id),
        parser_version=model.parser_version,
        profile_version=model.profile_version,
        input_checksum=model.input_checksum,
        pool_length_m=model.pool_length_m,
        distance_m=model.distance_m,
        elapsed_seconds=Decimal(model.elapsed_seconds),
        timer_seconds=Decimal(model.timer_seconds),
        moving_seconds=(None if legacy_v1 else _optional_decimal(model.moving_seconds)),
        active_length_count=model.active_length_count,
        completeness=Decimal(model.completeness),
        quality=DataQuality(model.quality),
        warnings=warnings,
        created_at=model.created_at,
        swim_seconds=_optional_decimal(model.swim_seconds),
        rest_seconds=_optional_decimal(model.rest_seconds),
        stationary_seconds=_optional_decimal(model.stationary_seconds),
        garmin_reported_speed_m_per_s=_optional_decimal(model.garmin_reported_speed_m_per_s),
        pace_from_garmin_reported_speed_seconds_per_100m=_optional_decimal(
            model.pace_from_garmin_reported_speed_seconds_per_100m
        ),
        moving_pace_seconds_per_100m=_optional_decimal(model.moving_pace_seconds_per_100m),
        swim_pace_seconds_per_100m=_optional_decimal(model.swim_pace_seconds_per_100m),
        timer_pace_seconds_per_100m=_optional_decimal(model.timer_pace_seconds_per_100m),
        session_pace_seconds_per_100m=_optional_decimal(model.session_pace_seconds_per_100m),
        provenance=_json(provenance),
    )


def _feedback(model: SessionFeedbackModel) -> SessionFeedback:
    return SessionFeedback(
        id=EntityId(model.id),
        user_id=UserId(model.user_id),
        activity_id=EntityId(model.activity_id),
        rpe=model.rpe,
        technique_rating=model.technique_rating,
        fatigue_rating=model.fatigue_rating,
        enjoyment_rating=model.enjoyment_rating,
        pain_present=model.pain_present,
        pain_location=model.pain_location,
        pain_intensity=model.pain_intensity,
        comment=model.comment,
        created_at=model.created_at,
        updated_at=model.updated_at,
        version=model.version,
    )


class SqlAlchemyUsersRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: UserId) -> AppUser | None:
        model = await self._session.get(AppUserModel, user_id.value)
        return _user(model) if model else None

    async def get_by_email(self, email: str) -> AppUser | None:
        statement = select(AppUserModel).where(AppUserModel.email.ilike(email.strip()))
        model = (await self._session.scalars(statement)).one_or_none()
        return _user(model) if model else None

    async def add(self, user: AppUser) -> None:
        self._session.add(
            AppUserModel(
                id=user.id.value,
                email=user.email,
                display_name=user.display_name,
                locale=user.locale,
                timezone=user.timezone,
                status=user.status.value,
                last_login_at=user.last_login_at,
                created_at=user.created_at,
                updated_at=user.updated_at,
                version=user.version,
            )
        )

    async def update(self, user: AppUser, *, expected_version: int) -> None:
        statement = (
            update(AppUserModel)
            .where(AppUserModel.id == user.id.value, AppUserModel.version == expected_version)
            .values(
                email=user.email,
                display_name=user.display_name,
                locale=user.locale,
                timezone=user.timezone,
                status=user.status.value,
                last_login_at=user.last_login_at,
                updated_at=user.updated_at,
                version=user.version,
            )
            .returning(AppUserModel.version)
        )
        if (await self._session.scalar(statement)) is None:
            raise RevisionConflictError(expected_version)

    async def list_active(self) -> Sequence[AppUser]:
        statement = select(AppUserModel).where(AppUserModel.status == UserStatus.ACTIVE.value)
        return [_user(model) for model in await self._session.scalars(statement)]


class SqlAlchemyIdentitiesRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, provider: str, subject: str) -> AuthIdentity | None:
        statement = select(AuthIdentityModel).where(
            AuthIdentityModel.provider == provider.casefold(), AuthIdentityModel.subject == subject
        )
        model = (await self._session.scalars(statement)).one_or_none()
        if model is None:
            return None
        return AuthIdentity(
            id=EntityId(model.id),
            user_id=UserId(model.user_id),
            provider=model.provider,
            subject=model.subject,
            claims_snapshot=_json(model.claims_json),
            created_at=model.created_at,
        )

    async def add(self, identity: AuthIdentity) -> None:
        self._session.add(
            AuthIdentityModel(
                id=identity.id.value,
                user_id=identity.user_id.value,
                provider=identity.provider,
                subject=identity.subject,
                claims_json=identity.claims_snapshot,
                created_at=identity.created_at,
                version=1,
            )
        )


class SqlAlchemyProfilesRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: UserId) -> AthleteProfile | None:
        model = await self._session.get(AthleteProfileModel, user_id.value)
        return _profile(model) if model else None

    async def add(self, profile: AthleteProfile) -> None:
        self._session.add(
            AthleteProfileModel(
                user_id=profile.user_id.value,
                experience_level=profile.experience_level,
                preferred_distance_unit=profile.preferred_distance_unit,
                default_pool_id=profile.default_pool_id.value if profile.default_pool_id else None,
                default_sessions_per_week=profile.default_sessions_per_week,
                goal_notes=profile.goal_notes,
                coach_preferences_json=profile.coach_preferences,
                created_at=profile.created_at,
                updated_at=profile.updated_at,
                version=profile.version,
            )
        )

    async def update(self, profile: AthleteProfile, *, expected_version: int) -> None:
        statement = (
            update(AthleteProfileModel)
            .where(
                AthleteProfileModel.user_id == profile.user_id.value,
                AthleteProfileModel.version == expected_version,
            )
            .values(
                experience_level=profile.experience_level,
                preferred_distance_unit=profile.preferred_distance_unit,
                default_pool_id=profile.default_pool_id.value if profile.default_pool_id else None,
                default_sessions_per_week=profile.default_sessions_per_week,
                goal_notes=profile.goal_notes,
                coach_preferences_json=profile.coach_preferences,
                updated_at=profile.updated_at,
                version=profile.version,
            )
            .returning(AthleteProfileModel.version)
        )
        if (await self._session.scalar(statement)) is None:
            raise RevisionConflictError(expected_version)


class SqlAlchemyPoolsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list(self, user_id: UserId) -> Sequence[Pool]:
        statement = (
            select(PoolModel)
            .where(PoolModel.user_id == user_id.value)
            .order_by(PoolModel.is_default.desc(), PoolModel.name)
        )
        return [_pool(model) for model in await self._session.scalars(statement)]

    async def get(self, user_id: UserId, pool_id: EntityId) -> Pool | None:
        statement = select(PoolModel).where(
            PoolModel.id == pool_id.value, PoolModel.user_id == user_id.value
        )
        model = (await self._session.scalars(statement)).one_or_none()
        return _pool(model) if model else None

    async def add(self, pool: Pool) -> None:
        self._session.add(
            PoolModel(
                id=pool.id.value,
                user_id=pool.user_id.value,
                name=pool.name,
                length_m=pool.length.meters,
                is_default=pool.is_default,
                location_label=pool.location_label,
                active=pool.active,
                created_at=pool.created_at,
                updated_at=pool.updated_at,
                version=pool.version,
            )
        )

    async def update(self, pool: Pool, *, expected_version: int) -> None:
        statement = (
            update(PoolModel)
            .where(PoolModel.id == pool.id.value, PoolModel.version == expected_version)
            .values(
                name=pool.name,
                length_m=pool.length.meters,
                is_default=pool.is_default,
                location_label=pool.location_label,
                active=pool.active,
                updated_at=pool.updated_at,
                version=pool.version,
            )
            .returning(PoolModel.version)
        )
        if (await self._session.scalar(statement)) is None:
            raise RevisionConflictError(expected_version)

    async def clear_default(self, user_id: UserId, *, except_id: EntityId) -> None:
        await self._session.execute(
            update(PoolModel)
            .where(
                PoolModel.user_id == user_id.value,
                PoolModel.id != except_id.value,
                PoolModel.is_default.is_(True),
            )
            .values(is_default=False, version=PoolModel.version + 1)
        )


class SqlAlchemyAvailabilityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list(self, user_id: UserId) -> Sequence[AvailabilityRule]:
        statement = (
            select(AvailabilityRuleModel)
            .where(AvailabilityRuleModel.user_id == user_id.value)
            .order_by(AvailabilityRuleModel.day_of_week, AvailabilityRuleModel.start_local_time)
        )
        return [_availability(model) for model in await self._session.scalars(statement)]

    async def replace(self, user_id: UserId, rules: Sequence[AvailabilityRule]) -> None:
        await self._session.execute(
            delete(AvailabilityRuleModel).where(AvailabilityRuleModel.user_id == user_id.value)
        )
        self._session.add_all(
            [
                AvailabilityRuleModel(
                    id=rule.id.value,
                    user_id=rule.user_id.value,
                    day_of_week=rule.day_of_week,
                    start_local_time=rule.start_local_time,
                    end_local_time=rule.end_local_time,
                    max_duration_minutes=rule.max_duration_minutes,
                    pool_id=rule.pool_id.value if rule.pool_id else None,
                    valid_from=rule.valid_from,
                    valid_until=rule.valid_until,
                    priority=rule.priority,
                    created_at=rule.created_at,
                    updated_at=rule.updated_at,
                    version=rule.version,
                )
                for rule in rules
            ]
        )


class SqlAlchemyConstraintsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list(self, user_id: UserId) -> Sequence[AthleteConstraint]:
        statement = select(AthleteConstraintModel).where(
            AthleteConstraintModel.user_id == user_id.value
        )
        return [_constraint(model) for model in await self._session.scalars(statement)]

    async def add(self, constraint: AthleteConstraint) -> None:
        self._session.add(
            AthleteConstraintModel(
                id=constraint.id.value,
                user_id=constraint.user_id.value,
                type=constraint.constraint_type.value,
                severity=constraint.severity,
                active_from=constraint.active_from,
                active_until=constraint.active_until,
                notes=constraint.notes,
                is_active=constraint.is_active,
                created_at=constraint.created_at,
                updated_at=constraint.updated_at,
                version=constraint.version,
            )
        )


class SqlAlchemyDevicesRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list(self, user_id: UserId) -> Sequence[Device]:
        statement = select(DeviceModel).where(DeviceModel.user_id == user_id.value)
        return [_device(model) for model in await self._session.scalars(statement)]

    async def add(self, device: Device) -> None:
        self._session.add(
            DeviceModel(
                id=device.id.value,
                user_id=device.user_id.value,
                provider=device.provider,
                external_device_id=device.external_device_id,
                model=device.model,
                name=device.name,
                serial_hash=device.serial_hash,
                is_primary=device.is_primary,
                capabilities_json=device.capabilities,
                last_seen_at=device.last_seen_at,
                created_at=device.created_at,
                updated_at=device.updated_at,
                version=device.version,
            )
        )

    async def upsert(self, device: Device) -> None:
        statement = insert(DeviceModel).values(
            id=device.id.value,
            user_id=device.user_id.value,
            provider=device.provider,
            external_device_id=device.external_device_id,
            model=device.model,
            name=device.name,
            serial_hash=device.serial_hash,
            is_primary=device.is_primary,
            capabilities_json=device.capabilities,
            last_seen_at=device.last_seen_at,
            created_at=device.created_at,
            updated_at=device.updated_at,
            version=device.version,
        )
        await self._session.execute(
            statement.on_conflict_do_update(
                constraint="uq_device_provider_external",
                set_={
                    "user_id": statement.excluded.user_id,
                    "model": statement.excluded.model,
                    "name": statement.excluded.name,
                    "serial_hash": statement.excluded.serial_hash,
                    "is_primary": statement.excluded.is_primary,
                    "capabilities_json": statement.excluded.capabilities_json,
                    "last_seen_at": statement.excluded.last_seen_at,
                    "updated_at": statement.excluded.updated_at,
                    "version": DeviceModel.version + 1,
                },
            )
        )


class SqlAlchemyGarminConnectionsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: UserId) -> GarminConnection | None:
        model = await self._session.get(GarminConnectionModel, user_id.value)
        return _garmin_connection(model) if model else None

    async def upsert(self, connection: GarminConnection) -> None:
        secret = connection.encrypted_token
        statement = insert(GarminConnectionModel).values(
            user_id=connection.user_id.value,
            status=connection.status.value,
            account_label_masked=connection.account_label_masked,
            encrypted_token_bundle=secret.ciphertext if secret else None,
            token_nonce=secret.nonce if secret else None,
            token_key_version=secret.key_version if secret else None,
            provider_library_version=connection.provider_library_version,
            authenticated_at=connection.authenticated_at,
            last_refresh_at=connection.last_refresh_at,
            last_success_at=connection.last_success_at,
            last_error_code=connection.last_error_code,
            last_error_message_redacted=connection.last_error_message_redacted,
            created_at=connection.created_at,
            updated_at=connection.updated_at,
            version=connection.version,
        )
        await self._session.execute(
            statement.on_conflict_do_update(
                index_elements=[GarminConnectionModel.user_id],
                set_={
                    "status": statement.excluded.status,
                    "account_label_masked": statement.excluded.account_label_masked,
                    "encrypted_token_bundle": statement.excluded.encrypted_token_bundle,
                    "token_nonce": statement.excluded.token_nonce,
                    "token_key_version": statement.excluded.token_key_version,
                    "provider_library_version": statement.excluded.provider_library_version,
                    "authenticated_at": statement.excluded.authenticated_at,
                    "last_refresh_at": statement.excluded.last_refresh_at,
                    "last_success_at": statement.excluded.last_success_at,
                    "last_error_code": statement.excluded.last_error_code,
                    "last_error_message_redacted": statement.excluded.last_error_message_redacted,
                    "updated_at": statement.excluded.updated_at,
                    "version": GarminConnectionModel.version + 1,
                },
            )
        )

    async def update(self, connection: GarminConnection, *, expected_version: int) -> None:
        secret = connection.encrypted_token
        statement = (
            update(GarminConnectionModel)
            .where(
                GarminConnectionModel.user_id == connection.user_id.value,
                GarminConnectionModel.version == expected_version,
            )
            .values(
                status=connection.status.value,
                account_label_masked=connection.account_label_masked,
                encrypted_token_bundle=secret.ciphertext if secret else None,
                token_nonce=secret.nonce if secret else None,
                token_key_version=secret.key_version if secret else None,
                provider_library_version=connection.provider_library_version,
                authenticated_at=connection.authenticated_at,
                last_refresh_at=connection.last_refresh_at,
                last_success_at=connection.last_success_at,
                last_error_code=connection.last_error_code,
                last_error_message_redacted=connection.last_error_message_redacted,
                updated_at=connection.updated_at,
                version=connection.version,
            )
            .returning(GarminConnectionModel.version)
        )
        if (await self._session.scalar(statement)) is None:
            raise RevisionConflictError(expected_version)


class SqlAlchemySyncCursorsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: UserId, provider: str, entity_type: str) -> SyncCursor | None:
        statement = select(SyncCursorModel).where(
            SyncCursorModel.user_id == user_id.value,
            SyncCursorModel.provider == provider,
            SyncCursorModel.entity_type == entity_type,
        )
        model = (await self._session.scalars(statement)).one_or_none()
        return _sync_cursor(model) if model else None

    async def upsert(self, cursor: SyncCursor) -> None:
        statement = insert(SyncCursorModel).values(
            id=cursor.id.value,
            user_id=cursor.user_id.value,
            provider=cursor.provider,
            entity_type=cursor.entity_type,
            cursor_json=cursor.cursor,
            watermark_at=cursor.watermark_at,
            last_success_at=cursor.last_success_at,
            overlap_seconds=cursor.overlap_seconds,
            created_at=cursor.created_at,
            updated_at=cursor.updated_at,
            version=cursor.version,
        )
        await self._session.execute(
            statement.on_conflict_do_update(
                constraint="uq_sync_cursor_user_provider_entity",
                set_={
                    "cursor_json": statement.excluded.cursor_json,
                    "watermark_at": statement.excluded.watermark_at,
                    "last_success_at": statement.excluded.last_success_at,
                    "overlap_seconds": statement.excluded.overlap_seconds,
                    "updated_at": statement.excluded.updated_at,
                    "version": SyncCursorModel.version + 1,
                },
            )
        )


class SqlAlchemySyncRunsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, run: SyncRun) -> None:
        self._session.add(
            SyncRunModel(
                id=run.id.value,
                user_id=run.user_id.value,
                provider=run.provider,
                sync_type=run.sync_type,
                trigger=run.trigger,
                status=run.status.value,
                listed=run.listed,
                created=run.created,
                updated=run.updated,
                skipped=run.skipped,
                failed=run.failed,
                cursor_before_json=run.cursor_before,
                cursor_after_json=run.cursor_after,
                error_json_redacted=run.error,
                started_at=run.started_at,
                finished_at=run.finished_at,
                version=run.version,
            )
        )

    async def update(self, run: SyncRun, *, expected_version: int) -> None:
        statement = (
            update(SyncRunModel)
            .where(SyncRunModel.id == run.id.value, SyncRunModel.version == expected_version)
            .values(
                status=run.status.value,
                listed=run.listed,
                created=run.created,
                updated=run.updated,
                skipped=run.skipped,
                failed=run.failed,
                cursor_after_json=run.cursor_after,
                error_json_redacted=run.error,
                finished_at=run.finished_at,
                version=run.version,
            )
            .returning(SyncRunModel.version)
        )
        if (await self._session.scalar(statement)) is None:
            raise RevisionConflictError(expected_version)

    async def list_recent(self, user_id: UserId, *, limit: int = 20) -> Sequence[SyncRun]:
        statement = (
            select(SyncRunModel)
            .where(SyncRunModel.user_id == user_id.value)
            .order_by(SyncRunModel.started_at.desc())
            .limit(limit)
        )
        return [_sync_run(model) for model in await self._session.scalars(statement)]


class SqlAlchemyRawProviderPayloadsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: UserId, payload_id: EntityId) -> RawProviderPayload | None:
        statement = select(RawProviderPayloadModel).where(
            RawProviderPayloadModel.id == payload_id.value,
            RawProviderPayloadModel.user_id == user_id.value,
        )
        model = (await self._session.scalars(statement)).one_or_none()
        return _raw_provider_payload(model) if model is not None else None

    async def add_if_absent(self, payload: RawProviderPayload) -> EntityId:
        statement = (
            insert(RawProviderPayloadModel)
            .values(
                id=payload.id.value,
                user_id=payload.user_id.value,
                provider=payload.provider,
                entity_type=payload.entity_type,
                external_id=payload.external_id,
                content_type=payload.content_type,
                json_payload=payload.payload,
                checksum=payload.checksum,
                provider_updated_at=payload.provider_updated_at,
                received_at=payload.received_at,
            )
            .on_conflict_do_nothing(constraint="uq_raw_payload_identity_checksum")
            .returning(RawProviderPayloadModel.id)
        )
        inserted_id = await self._session.scalar(statement)
        if inserted_id is not None:
            return EntityId(inserted_id)
        existing_id = await self._session.scalar(
            select(RawProviderPayloadModel.id).where(
                RawProviderPayloadModel.user_id == payload.user_id.value,
                RawProviderPayloadModel.provider == payload.provider,
                RawProviderPayloadModel.entity_type == payload.entity_type,
                RawProviderPayloadModel.external_id == payload.external_id,
                RawProviderPayloadModel.checksum == payload.checksum,
            )
        )
        if existing_id is None:
            raise RuntimeError("raw payload conflict could not be resolved")
        return EntityId(existing_id)


class SqlAlchemyActivitiesRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: UserId, activity_id: EntityId) -> Activity | None:
        statement = select(ActivityModel).where(
            ActivityModel.id == activity_id.value,
            ActivityModel.user_id == user_id.value,
        )
        model = (await self._session.scalars(statement)).one_or_none()
        return _activity(model) if model else None

    async def get_by_external_id(
        self, user_id: UserId, provider: str, external_activity_id: str
    ) -> Activity | None:
        statement = select(ActivityModel).where(
            ActivityModel.user_id == user_id.value,
            ActivityModel.provider == provider,
            ActivityModel.external_activity_id == external_activity_id,
        )
        model = (await self._session.scalars(statement)).one_or_none()
        return _activity(model) if model else None

    async def upsert(self, activity: Activity) -> tuple[ActivityImportStatus, EntityId]:
        statement = (
            select(ActivityModel)
            .where(
                ActivityModel.user_id == activity.user_id.value,
                ActivityModel.provider == activity.provider,
                ActivityModel.external_activity_id == activity.external_activity_id,
            )
            .with_for_update()
        )
        model = (await self._session.scalars(statement)).one_or_none()
        if (
            model is not None
            and model.summary_checksum == activity.summary_checksum
            and model.normalization_version == activity.normalization_version
        ):
            return ActivityImportStatus.SKIPPED, EntityId(model.id)
        values = {
            "name": activity.name,
            "sport": activity.sport,
            "subtype": activity.subtype,
            "start_time_utc": activity.start_time_utc,
            "timezone": activity.timezone,
            "distance_m": activity.distance.meters,
            "elapsed_seconds": activity.elapsed.seconds,
            "timer_seconds": activity.timer.seconds,
            "moving_seconds": activity.moving.seconds,
            "pool_length_m": activity.pool_length.meters if activity.pool_length else None,
            "length_count": activity.length_count,
            "calories": activity.calories,
            "avg_hr": activity.avg_hr,
            "max_hr": activity.max_hr,
            "avg_pace_seconds_per_100m": activity.avg_pace_seconds_per_100m,
            "avg_stroke_rate": activity.avg_stroke_rate,
            "avg_strokes_per_length": activity.avg_strokes_per_length,
            "avg_swolf": activity.avg_swolf,
            "source_updated_at": activity.source_updated_at,
            "normalization_version": activity.normalization_version,
            "raw_summary_id": activity.raw_summary_id.value,
            "raw_fit_id": activity.raw_fit_id.value if activity.raw_fit_id else None,
            "summary_checksum": activity.summary_checksum,
            "updated_at": activity.updated_at,
        }
        if model is None:
            self._session.add(
                ActivityModel(
                    id=activity.id.value,
                    user_id=activity.user_id.value,
                    provider=activity.provider,
                    external_activity_id=activity.external_activity_id,
                    created_at=activity.created_at,
                    version=activity.version,
                    **values,
                )
            )
            return ActivityImportStatus.CREATED, activity.id
        for key, value in values.items():
            setattr(model, key, value)
        model.version += 1
        return ActivityImportStatus.UPDATED, EntityId(model.id)

    async def list_recent(
        self, user_id: UserId, *, limit: int = 50, before: datetime | None = None
    ) -> Sequence[Activity]:
        statement = select(ActivityModel).where(ActivityModel.user_id == user_id.value)
        if before is not None:
            statement = statement.where(ActivityModel.start_time_utc < before)
        statement = statement.order_by(ActivityModel.start_time_utc.desc()).limit(limit)
        return [_activity(model) for model in await self._session.scalars(statement)]

    async def list_all(self, user_id: UserId) -> Sequence[Activity]:
        statement = (
            select(ActivityModel)
            .where(ActivityModel.user_id == user_id.value)
            .order_by(ActivityModel.start_time_utc)
        )
        return [_activity(model) for model in await self._session.scalars(statement)]


class SqlAlchemyActivityDataRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_artifact_by_checksum(
        self, user_id: UserId, activity_id: EntityId, checksum: str, artifact_type: str
    ) -> FileArtifact | None:
        statement = select(FileArtifactModel).where(
            FileArtifactModel.user_id == user_id.value,
            FileArtifactModel.activity_id == activity_id.value,
            FileArtifactModel.checksum == checksum,
            FileArtifactModel.artifact_type == artifact_type,
        )
        model = (await self._session.scalars(statement)).one_or_none()
        if model is None:
            return None
        return _file_artifact(model)

    async def list_artifacts(self, user_id: UserId) -> Sequence[FileArtifact]:
        statement = (
            select(FileArtifactModel)
            .where(FileArtifactModel.user_id == user_id.value)
            .order_by(FileArtifactModel.created_at)
        )
        return [_file_artifact(model) for model in await self._session.scalars(statement)]

    async def add_artifact(self, artifact: FileArtifact) -> FileArtifact:
        statement = (
            insert(FileArtifactModel)
            .values(
                id=artifact.id.value,
                user_id=artifact.user_id.value,
                activity_id=artifact.activity_id.value,
                provider=artifact.provider,
                artifact_type=artifact.artifact_type,
                storage_key=artifact.storage_key,
                content_type=artifact.content_type,
                size_bytes=artifact.size_bytes,
                checksum=artifact.checksum,
                source_external_id_hash=artifact.source_external_id_hash,
                created_at=artifact.created_at,
            )
            .on_conflict_do_nothing(constraint="uq_file_artifact_activity_checksum_type")
            .returning(FileArtifactModel.id)
        )
        if await self._session.scalar(statement) is not None:
            return artifact
        winner = await self.get_artifact_by_checksum(
            artifact.user_id,
            artifact.activity_id,
            artifact.checksum,
            artifact.artifact_type,
        )
        if winner is None:
            raise RuntimeError("file artifact conflict could not be resolved")
        return winner

    async def _load_normalized(
        self, user_id: UserId, normalization_id: EntityId
    ) -> NormalizedActivity | None:
        statement = select(ActivityNormalizationModel).where(
            ActivityNormalizationModel.id == normalization_id.value,
            ActivityNormalizationModel.user_id == user_id.value,
        )
        model = (await self._session.scalars(statement)).one_or_none()
        if model is None:
            return None
        legacy_v1 = _is_legacy_v1_parser(model.parser_version)
        lap_models = await self._session.scalars(
            select(ActivityLapModel)
            .where(ActivityLapModel.normalization_id == normalization_id.value)
            .order_by(ActivityLapModel.lap_index)
        )
        interval_models = list(
            await self._session.scalars(
                select(ActivityIntervalModel)
                .where(ActivityIntervalModel.normalization_id == normalization_id.value)
                .order_by(ActivityIntervalModel.interval_index)
            )
        )
        length_models = await self._session.scalars(
            select(ActivityLengthModel)
            .where(ActivityLengthModel.normalization_id == normalization_id.value)
            .order_by(ActivityLengthModel.length_index)
        )
        laps = tuple(
            ActivityLap(
                id=EntityId(item.id),
                normalization_id=EntityId(item.normalization_id),
                lap_index=item.lap_index,
                start_offset_seconds=Decimal(item.start_offset_seconds),
                elapsed_seconds=Decimal(item.elapsed_seconds),
                timer_seconds=Decimal(item.timer_seconds),
                distance_m=item.distance_m,
                avg_hr_bpm=item.avg_hr_bpm,
                max_hr_bpm=item.max_hr_bpm,
                stroke_type=item.stroke_type,
                moving_seconds=_optional_decimal(item.moving_seconds),
                swim_seconds=_optional_decimal(item.swim_seconds),
                rest_seconds=_optional_decimal(item.rest_seconds),
                stationary_seconds=_optional_decimal(item.stationary_seconds),
                garmin_reported_speed_m_per_s=_optional_decimal(item.garmin_reported_speed_m_per_s),
                pace_from_garmin_reported_speed_seconds_per_100m=_optional_decimal(
                    item.pace_from_garmin_reported_speed_seconds_per_100m
                ),
                moving_pace_seconds_per_100m=_optional_decimal(item.moving_pace_seconds_per_100m),
                swim_pace_seconds_per_100m=_optional_decimal(item.swim_pace_seconds_per_100m),
                timer_pace_seconds_per_100m=_optional_decimal(item.timer_pace_seconds_per_100m),
                elapsed_pace_seconds_per_100m=_optional_decimal(item.elapsed_pace_seconds_per_100m),
                detected_stroke=item.detected_stroke,
                planned_stroke=item.planned_stroke,
                provenance=_legacy_child_provenance(
                    item.provenance_json,
                    legacy_v1=legacy_v1,
                ),
                quality_warnings=(
                    _with_warning(item.quality_warnings_json, _LEGACY_V1_CHILD_WARNING)
                    if legacy_v1
                    else tuple(item.quality_warnings_json)
                ),
            )
            for item in lap_models
        )
        intervals = tuple(
            ActivityInterval(
                id=EntityId(item.id),
                normalization_id=EntityId(item.normalization_id),
                interval_index=item.interval_index,
                interval_type=item.interval_type,
                start_offset_seconds=Decimal(item.start_offset_seconds),
                duration_seconds=Decimal(item.duration_seconds),
                rest_seconds=Decimal(item.rest_seconds),
                distance_m=item.distance_m,
                pace_seconds_per_100m=(
                    Decimal(item.pace_seconds_per_100m)
                    if item.pace_seconds_per_100m is not None
                    else None
                ),
                avg_hr_bpm=item.avg_hr_bpm,
                max_hr_bpm=item.max_hr_bpm,
                stroke_type=item.stroke_type,
                stroke_count=item.stroke_count,
                stroke_rate=Decimal(item.stroke_rate) if item.stroke_rate is not None else None,
                swolf=Decimal(item.swolf) if item.swolf is not None else None,
                source=_json(item.source_json),
                elapsed_seconds=_optional_decimal(item.elapsed_seconds),
                timer_seconds=_optional_decimal(item.timer_seconds),
                moving_seconds=_optional_decimal(item.moving_seconds),
                swim_seconds=_optional_decimal(item.swim_seconds),
                stationary_seconds=_optional_decimal(item.stationary_seconds),
                garmin_reported_speed_m_per_s=_optional_decimal(item.garmin_reported_speed_m_per_s),
                pace_from_garmin_reported_speed_seconds_per_100m=_optional_decimal(
                    item.pace_from_garmin_reported_speed_seconds_per_100m
                ),
                moving_pace_seconds_per_100m=_optional_decimal(item.moving_pace_seconds_per_100m),
                swim_pace_seconds_per_100m=_optional_decimal(item.swim_pace_seconds_per_100m),
                timer_pace_seconds_per_100m=_optional_decimal(item.timer_pace_seconds_per_100m),
                elapsed_pace_seconds_per_100m=_optional_decimal(item.elapsed_pace_seconds_per_100m),
                planned_role=item.planned_role,
                detected_stroke=item.detected_stroke,
                planned_stroke=item.planned_stroke,
                provenance=_legacy_child_provenance(
                    item.provenance_json,
                    legacy_v1=legacy_v1,
                ),
                quality_warnings=(
                    _with_warning(item.quality_warnings_json, _LEGACY_V1_CHILD_WARNING)
                    if legacy_v1
                    else tuple(item.quality_warnings_json)
                ),
            )
            for item in interval_models
        )
        lengths = tuple(
            ActivityLength(
                id=EntityId(item.id),
                normalization_id=EntityId(item.normalization_id),
                interval_id=EntityId(item.interval_id),
                length_index=item.length_index,
                distance_m=item.distance_m,
                duration_seconds=Decimal(item.duration_seconds),
                stroke_type=item.stroke_type,
                stroke_count=item.stroke_count,
                stroke_rate=Decimal(item.stroke_rate) if item.stroke_rate is not None else None,
                swolf=Decimal(item.swolf) if item.swolf is not None else None,
                avg_hr_bpm=item.avg_hr_bpm,
                length_type=item.length_type,
                elapsed_seconds=_optional_decimal(item.elapsed_seconds),
                timer_seconds=_optional_decimal(item.timer_seconds),
                moving_seconds=_optional_decimal(item.moving_seconds),
                swim_seconds=_optional_decimal(item.swim_seconds),
                rest_seconds=_optional_decimal(item.rest_seconds),
                stationary_seconds=_optional_decimal(item.stationary_seconds),
                garmin_reported_speed_m_per_s=_optional_decimal(item.garmin_reported_speed_m_per_s),
                pace_from_garmin_reported_speed_seconds_per_100m=_optional_decimal(
                    item.pace_from_garmin_reported_speed_seconds_per_100m
                ),
                moving_pace_seconds_per_100m=_optional_decimal(item.moving_pace_seconds_per_100m),
                swim_pace_seconds_per_100m=_optional_decimal(item.swim_pace_seconds_per_100m),
                timer_pace_seconds_per_100m=_optional_decimal(item.timer_pace_seconds_per_100m),
                elapsed_pace_seconds_per_100m=_optional_decimal(item.elapsed_pace_seconds_per_100m),
                detected_stroke=item.detected_stroke,
                planned_stroke=item.planned_stroke,
                provenance=_legacy_child_provenance(
                    item.provenance_json,
                    legacy_v1=legacy_v1,
                ),
                quality_warnings=(
                    _with_warning(item.quality_warnings_json, _LEGACY_V1_CHILD_WARNING)
                    if legacy_v1
                    else tuple(item.quality_warnings_json)
                ),
            )
            for item in length_models
        )
        return NormalizedActivity(_normalization(model), laps, intervals, lengths)

    async def get_normalization(
        self, user_id: UserId, normalization_id: EntityId
    ) -> NormalizedActivity | None:
        return await self._load_normalized(user_id, normalization_id)

    async def get_current_normalization(
        self, user_id: UserId, activity_id: EntityId
    ) -> NormalizedActivity | None:
        normalization_id = await self._session.scalar(
            select(ActivityModel.current_normalization_id).where(
                ActivityModel.id == activity_id.value,
                ActivityModel.user_id == user_id.value,
            )
        )
        return (
            await self._load_normalized(user_id, EntityId(normalization_id))
            if normalization_id is not None
            else None
        )

    async def list_current_normalization_facts(
        self, user_id: UserId, activity_ids: Sequence[EntityId]
    ) -> Sequence[ActivityNormalization]:
        """Load canonical session facts in one query, without lap/interval children."""

        if not activity_ids:
            return []
        statement = (
            select(ActivityNormalizationModel)
            .join(
                ActivityModel,
                ActivityModel.current_normalization_id == ActivityNormalizationModel.id,
            )
            .where(
                ActivityModel.user_id == user_id.value,
                ActivityModel.id.in_([item.value for item in activity_ids]),
                ActivityNormalizationModel.user_id == user_id.value,
            )
        )
        return [_normalization(model) for model in await self._session.scalars(statement)]

    async def get_normalization_by_input(
        self,
        user_id: UserId,
        activity_id: EntityId,
        parser_version: str,
        input_checksum: str,
    ) -> NormalizedActivity | None:
        normalization_id = await self._session.scalar(
            select(ActivityNormalizationModel.id).where(
                ActivityNormalizationModel.user_id == user_id.value,
                ActivityNormalizationModel.activity_id == activity_id.value,
                ActivityNormalizationModel.parser_version == parser_version,
                ActivityNormalizationModel.input_checksum == input_checksum,
            )
        )
        return (
            await self._load_normalized(user_id, EntityId(normalization_id))
            if normalization_id is not None
            else None
        )

    async def save_normalization(self, normalized: NormalizedActivity) -> bool:
        item = normalized.normalization
        statement = (
            insert(ActivityNormalizationModel)
            .values(
                id=item.id.value,
                user_id=item.user_id.value,
                activity_id=item.activity_id.value,
                artifact_id=item.artifact_id.value,
                parser_version=item.parser_version,
                profile_version=item.profile_version,
                input_checksum=item.input_checksum,
                pool_length_m=item.pool_length_m,
                distance_m=item.distance_m,
                elapsed_seconds=item.elapsed_seconds,
                timer_seconds=item.timer_seconds,
                moving_seconds=item.moving_seconds,
                swim_seconds=item.swim_seconds,
                rest_seconds=item.rest_seconds,
                stationary_seconds=item.stationary_seconds,
                garmin_reported_speed_m_per_s=item.garmin_reported_speed_m_per_s,
                pace_from_garmin_reported_speed_seconds_per_100m=(
                    item.pace_from_garmin_reported_speed_seconds_per_100m
                ),
                moving_pace_seconds_per_100m=item.moving_pace_seconds_per_100m,
                swim_pace_seconds_per_100m=item.swim_pace_seconds_per_100m,
                timer_pace_seconds_per_100m=item.timer_pace_seconds_per_100m,
                session_pace_seconds_per_100m=item.session_pace_seconds_per_100m,
                active_length_count=item.active_length_count,
                completeness=item.completeness,
                quality=item.quality.value,
                warnings_json=list(item.warnings),
                provenance_json=item.provenance,
                created_at=item.created_at,
            )
            .on_conflict_do_nothing(constraint="uq_activity_normalization_input_version")
            .returning(ActivityNormalizationModel.id)
        )
        if await self._session.scalar(statement) is None:
            return False
        self._session.add_all(
            [
                ActivityLapModel(
                    id=lap.id.value,
                    normalization_id=lap.normalization_id.value,
                    lap_index=lap.lap_index,
                    start_offset_seconds=lap.start_offset_seconds,
                    elapsed_seconds=lap.elapsed_seconds,
                    timer_seconds=lap.timer_seconds,
                    moving_seconds=lap.moving_seconds,
                    swim_seconds=lap.swim_seconds,
                    rest_seconds=lap.rest_seconds,
                    stationary_seconds=lap.stationary_seconds,
                    distance_m=lap.distance_m,
                    avg_hr_bpm=lap.avg_hr_bpm,
                    max_hr_bpm=lap.max_hr_bpm,
                    stroke_type=lap.stroke_type,
                    detected_stroke=lap.detected_stroke,
                    planned_stroke=lap.planned_stroke,
                    garmin_reported_speed_m_per_s=lap.garmin_reported_speed_m_per_s,
                    pace_from_garmin_reported_speed_seconds_per_100m=(
                        lap.pace_from_garmin_reported_speed_seconds_per_100m
                    ),
                    moving_pace_seconds_per_100m=lap.moving_pace_seconds_per_100m,
                    swim_pace_seconds_per_100m=lap.swim_pace_seconds_per_100m,
                    timer_pace_seconds_per_100m=lap.timer_pace_seconds_per_100m,
                    elapsed_pace_seconds_per_100m=lap.elapsed_pace_seconds_per_100m,
                    provenance_json=lap.provenance,
                    quality_warnings_json=list(lap.quality_warnings),
                )
                for lap in normalized.laps
            ]
        )
        self._session.add_all(
            [
                ActivityIntervalModel(
                    id=interval.id.value,
                    normalization_id=interval.normalization_id.value,
                    interval_index=interval.interval_index,
                    interval_type=interval.interval_type,
                    start_offset_seconds=interval.start_offset_seconds,
                    duration_seconds=interval.duration_seconds,
                    rest_seconds=interval.rest_seconds,
                    elapsed_seconds=interval.elapsed_seconds,
                    timer_seconds=interval.timer_seconds,
                    moving_seconds=interval.moving_seconds,
                    swim_seconds=interval.swim_seconds,
                    stationary_seconds=interval.stationary_seconds,
                    distance_m=interval.distance_m,
                    pace_seconds_per_100m=interval.pace_seconds_per_100m,
                    garmin_reported_speed_m_per_s=interval.garmin_reported_speed_m_per_s,
                    pace_from_garmin_reported_speed_seconds_per_100m=(
                        interval.pace_from_garmin_reported_speed_seconds_per_100m
                    ),
                    moving_pace_seconds_per_100m=(interval.moving_pace_seconds_per_100m),
                    swim_pace_seconds_per_100m=interval.swim_pace_seconds_per_100m,
                    timer_pace_seconds_per_100m=interval.timer_pace_seconds_per_100m,
                    elapsed_pace_seconds_per_100m=interval.elapsed_pace_seconds_per_100m,
                    avg_hr_bpm=interval.avg_hr_bpm,
                    max_hr_bpm=interval.max_hr_bpm,
                    stroke_type=interval.stroke_type,
                    detected_stroke=interval.detected_stroke,
                    planned_stroke=interval.planned_stroke,
                    planned_role=interval.planned_role,
                    stroke_count=interval.stroke_count,
                    stroke_rate=interval.stroke_rate,
                    swolf=interval.swolf,
                    source_json=interval.source,
                    provenance_json=interval.provenance,
                    quality_warnings_json=list(interval.quality_warnings),
                )
                for interval in normalized.intervals
            ]
        )
        self._session.add_all(
            [
                ActivityLengthModel(
                    id=length.id.value,
                    normalization_id=length.normalization_id.value,
                    interval_id=length.interval_id.value,
                    length_index=length.length_index,
                    distance_m=length.distance_m,
                    duration_seconds=length.duration_seconds,
                    length_type=length.length_type,
                    elapsed_seconds=length.elapsed_seconds,
                    timer_seconds=length.timer_seconds,
                    moving_seconds=length.moving_seconds,
                    swim_seconds=length.swim_seconds,
                    rest_seconds=length.rest_seconds,
                    stationary_seconds=length.stationary_seconds,
                    stroke_type=length.stroke_type,
                    detected_stroke=length.detected_stroke,
                    planned_stroke=length.planned_stroke,
                    garmin_reported_speed_m_per_s=length.garmin_reported_speed_m_per_s,
                    pace_from_garmin_reported_speed_seconds_per_100m=(
                        length.pace_from_garmin_reported_speed_seconds_per_100m
                    ),
                    moving_pace_seconds_per_100m=length.moving_pace_seconds_per_100m,
                    swim_pace_seconds_per_100m=length.swim_pace_seconds_per_100m,
                    timer_pace_seconds_per_100m=length.timer_pace_seconds_per_100m,
                    elapsed_pace_seconds_per_100m=length.elapsed_pace_seconds_per_100m,
                    stroke_count=length.stroke_count,
                    stroke_rate=length.stroke_rate,
                    swolf=length.swolf,
                    avg_hr_bpm=length.avg_hr_bpm,
                    provenance_json=length.provenance,
                    quality_warnings_json=list(length.quality_warnings),
                )
                for length in normalized.lengths
            ]
        )
        return True

    async def promote_normalization(
        self,
        user_id: UserId,
        activity_id: EntityId,
        normalization_id: EntityId,
        analysis_id: EntityId,
    ) -> None:
        owned_normalization = exists(
            select(ActivityNormalizationModel.id).where(
                ActivityNormalizationModel.id == normalization_id.value,
                ActivityNormalizationModel.user_id == user_id.value,
                ActivityNormalizationModel.activity_id == activity_id.value,
            )
        )
        matching_analysis = exists(
            select(ActivityAnalysisModel.id).where(
                ActivityAnalysisModel.id == analysis_id.value,
                ActivityAnalysisModel.user_id == user_id.value,
                ActivityAnalysisModel.activity_id == activity_id.value,
                ActivityAnalysisModel.normalization_id == normalization_id.value,
            )
        )
        statement = (
            update(ActivityModel)
            .where(
                ActivityModel.id == activity_id.value,
                ActivityModel.user_id == user_id.value,
                owned_normalization,
                matching_analysis,
            )
            .values(
                current_normalization_id=normalization_id.value,
                current_analysis_id=analysis_id.value,
            )
            .returning(ActivityModel.id)
        )
        if await self._session.scalar(statement) is None:
            raise RevisionConflictError(1)

    async def get_analysis(self, user_id: UserId, activity_id: EntityId) -> ActivityAnalysis | None:
        statement = (
            select(ActivityAnalysisModel)
            .join(
                ActivityModel,
                and_(
                    ActivityModel.id == activity_id.value,
                    ActivityModel.user_id == user_id.value,
                    ActivityModel.current_normalization_id
                    == ActivityAnalysisModel.normalization_id,
                    ActivityModel.current_analysis_id == ActivityAnalysisModel.id,
                ),
            )
            .where(
                ActivityAnalysisModel.user_id == user_id.value,
                ActivityAnalysisModel.activity_id == activity_id.value,
            )
        )
        model = (await self._session.scalars(statement)).one_or_none()
        if model is None:
            return None
        return _analysis(model)

    async def get_analysis_by_context(
        self,
        user_id: UserId,
        activity_id: EntityId,
        normalization_id: EntityId,
        analysis_version: str,
        planned_workout_id: EntityId | None,
    ) -> ActivityAnalysis | None:
        target = (
            ActivityAnalysisModel.planned_workout_id.is_(None)
            if planned_workout_id is None
            else ActivityAnalysisModel.planned_workout_id == planned_workout_id.value
        )
        statement = select(ActivityAnalysisModel).where(
            ActivityAnalysisModel.user_id == user_id.value,
            ActivityAnalysisModel.activity_id == activity_id.value,
            ActivityAnalysisModel.normalization_id == normalization_id.value,
            ActivityAnalysisModel.analysis_version == analysis_version,
            target,
        )
        model = (await self._session.scalars(statement)).one_or_none()
        return _analysis(model) if model is not None else None

    async def list_analyses(
        self, user_id: UserId, activity_ids: Sequence[EntityId]
    ) -> Sequence[ActivityAnalysis]:
        if not activity_ids:
            return []
        statement = (
            select(ActivityAnalysisModel)
            .join(
                ActivityModel,
                and_(
                    ActivityModel.user_id == user_id.value,
                    ActivityModel.id.in_([item.value for item in activity_ids]),
                    ActivityModel.current_normalization_id
                    == ActivityAnalysisModel.normalization_id,
                    ActivityModel.current_analysis_id == ActivityAnalysisModel.id,
                ),
            )
            .where(ActivityAnalysisModel.user_id == user_id.value)
        )
        return [_analysis(model) for model in await self._session.scalars(statement)]

    async def add_analysis(self, analysis: ActivityAnalysis) -> ActivityAnalysis:
        statement = (
            insert(ActivityAnalysisModel)
            .values(
                id=analysis.id.value,
                user_id=analysis.user_id.value,
                activity_id=analysis.activity_id.value,
                normalization_id=analysis.normalization_id.value,
                planned_workout_id=(
                    analysis.planned_workout_id.value if analysis.planned_workout_id else None
                ),
                analysis_version=analysis.analysis_version,
                parser_version=analysis.parser_version,
                input_checksum=analysis.input_checksum,
                pool_length_m=analysis.pool_length_m,
                metrics_json=analysis.metrics,
                flags_json=list(analysis.flags),
                quality=analysis.quality.value,
                summary_json=analysis.summary,
                created_at=analysis.created_at,
            )
            .on_conflict_do_nothing(
                index_elements=(
                    ActivityAnalysisModel.normalization_id,
                    ActivityAnalysisModel.analysis_version,
                    text(
                        "coalesce(planned_workout_id, '00000000-0000-0000-0000-000000000000'::uuid)"
                    ),
                )
            )
            .returning(ActivityAnalysisModel.id)
        )
        if await self._session.scalar(statement) is not None:
            return analysis
        winner = await self.get_analysis_by_context(
            analysis.user_id,
            analysis.activity_id,
            analysis.normalization_id,
            analysis.analysis_version,
            analysis.planned_workout_id,
        )
        if winner is None:
            raise RuntimeError("activity analysis conflict could not be resolved")
        return winner

    async def get_match(
        self, user_id: UserId, activity_id: EntityId
    ) -> WorkoutExecutionMatch | None:
        statement = select(WorkoutExecutionMatchModel).where(
            WorkoutExecutionMatchModel.user_id == user_id.value,
            WorkoutExecutionMatchModel.activity_id == activity_id.value,
        )
        model = (await self._session.scalars(statement)).one_or_none()
        if model is None:
            return None
        return WorkoutExecutionMatch(
            id=EntityId(model.id),
            user_id=UserId(model.user_id),
            activity_id=EntityId(model.activity_id),
            planned_workout_id=EntityId(model.planned_workout_id),
            method=model.method,
            confidence=Decimal(model.confidence),
            score_details=_json(model.score_details_json),
            confirmed_at=model.confirmed_at,
            confirmed_by=model.confirmed_by,
            created_at=model.created_at,
        )

    async def get_match_by_workout(
        self, user_id: UserId, workout_id: EntityId
    ) -> WorkoutExecutionMatch | None:
        statement = select(WorkoutExecutionMatchModel).where(
            WorkoutExecutionMatchModel.user_id == user_id.value,
            WorkoutExecutionMatchModel.planned_workout_id == workout_id.value,
        )
        model = (await self._session.scalars(statement)).one_or_none()
        if model is None:
            return None
        return WorkoutExecutionMatch(
            id=EntityId(model.id),
            user_id=UserId(model.user_id),
            activity_id=EntityId(model.activity_id),
            planned_workout_id=EntityId(model.planned_workout_id),
            method=model.method,
            confidence=Decimal(model.confidence),
            score_details=_json(model.score_details_json),
            confirmed_at=model.confirmed_at,
            confirmed_by=model.confirmed_by,
            created_at=model.created_at,
        )

    async def upsert_match(self, match: WorkoutExecutionMatch) -> None:
        statement = insert(WorkoutExecutionMatchModel).values(
            id=match.id.value,
            user_id=match.user_id.value,
            activity_id=match.activity_id.value,
            planned_workout_id=match.planned_workout_id.value,
            method=match.method,
            confidence=match.confidence,
            score_details_json=match.score_details,
            confirmed_at=match.confirmed_at,
            confirmed_by=match.confirmed_by,
            created_at=match.created_at,
        )
        await self._session.execute(
            statement.on_conflict_do_update(
                constraint="uq_workout_execution_match_activity",
                set_={
                    "planned_workout_id": statement.excluded.planned_workout_id,
                    "method": statement.excluded.method,
                    "confidence": statement.excluded.confidence,
                    "score_details_json": statement.excluded.score_details_json,
                    "confirmed_at": statement.excluded.confirmed_at,
                    "confirmed_by": statement.excluded.confirmed_by,
                },
            )
        )

    async def get_feedback(self, user_id: UserId, activity_id: EntityId) -> SessionFeedback | None:
        statement = select(SessionFeedbackModel).where(
            SessionFeedbackModel.user_id == user_id.value,
            SessionFeedbackModel.activity_id == activity_id.value,
        )
        model = (await self._session.scalars(statement)).one_or_none()
        return _feedback(model) if model else None

    async def list_feedbacks(
        self, user_id: UserId, activity_ids: Sequence[EntityId]
    ) -> Sequence[SessionFeedback]:
        if not activity_ids:
            return []
        statement = select(SessionFeedbackModel).where(
            SessionFeedbackModel.user_id == user_id.value,
            SessionFeedbackModel.activity_id.in_([item.value for item in activity_ids]),
        )
        return [_feedback(model) for model in await self._session.scalars(statement)]

    async def upsert_feedback(
        self, feedback: SessionFeedback, *, expected_version: int | None
    ) -> None:
        if expected_version is None:
            self._session.add(
                SessionFeedbackModel(
                    id=feedback.id.value,
                    user_id=feedback.user_id.value,
                    activity_id=feedback.activity_id.value,
                    rpe=feedback.rpe,
                    technique_rating=feedback.technique_rating,
                    fatigue_rating=feedback.fatigue_rating,
                    enjoyment_rating=feedback.enjoyment_rating,
                    pain_present=feedback.pain_present,
                    pain_location=feedback.pain_location,
                    pain_intensity=feedback.pain_intensity,
                    comment=feedback.comment,
                    created_at=feedback.created_at,
                    updated_at=feedback.updated_at,
                    version=feedback.version,
                )
            )
            return
        statement = (
            update(SessionFeedbackModel)
            .where(
                SessionFeedbackModel.id == feedback.id.value,
                SessionFeedbackModel.user_id == feedback.user_id.value,
                SessionFeedbackModel.version == expected_version,
            )
            .values(
                rpe=feedback.rpe,
                technique_rating=feedback.technique_rating,
                fatigue_rating=feedback.fatigue_rating,
                enjoyment_rating=feedback.enjoyment_rating,
                pain_present=feedback.pain_present,
                pain_location=feedback.pain_location,
                pain_intensity=feedback.pain_intensity,
                comment=feedback.comment,
                updated_at=feedback.updated_at,
                version=feedback.version,
            )
            .returning(SessionFeedbackModel.version)
        )
        if await self._session.scalar(statement) is None:
            raise RevisionConflictError(expected_version)


class SqlAlchemyActivityImportsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, activity_import: ActivityImport) -> None:
        self._session.add(
            ActivityImportModel(
                id=activity_import.id.value,
                user_id=activity_import.user_id.value,
                sync_run_id=activity_import.sync_run_id.value,
                activity_id=(
                    activity_import.activity_id.value if activity_import.activity_id else None
                ),
                external_activity_id=activity_import.external_activity_id,
                status=activity_import.status.value,
                checksum=activity_import.checksum,
                error_code=activity_import.error_code,
                created_at=activity_import.created_at,
            )
        )


class SqlAlchemyGoalsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list(self, user_id: UserId) -> Sequence[TrainingGoal]:
        statement = (
            select(TrainingGoalModel)
            .where(TrainingGoalModel.user_id == user_id.value)
            .order_by(TrainingGoalModel.priority, TrainingGoalModel.created_at)
        )
        return [_goal(model) for model in await self._session.scalars(statement)]

    async def get(self, user_id: UserId, goal_id: EntityId) -> TrainingGoal | None:
        statement = select(TrainingGoalModel).where(
            TrainingGoalModel.id == goal_id.value,
            TrainingGoalModel.user_id == user_id.value,
        )
        model = (await self._session.scalars(statement)).one_or_none()
        return _goal(model) if model else None

    async def add(self, goal: TrainingGoal) -> None:
        self._session.add(
            TrainingGoalModel(
                id=goal.id.value,
                user_id=goal.user_id.value,
                type=goal.goal_type,
                title=goal.title,
                status=goal.status.value,
                priority=goal.priority,
                target_distance_m=goal.target_distance.meters,
                target_duration_seconds=goal.target_duration.seconds,
                target_date=goal.target_date,
                target_pace_seconds_per_100m=goal.target_pace.seconds_per_100m,
                baseline_json=goal.baseline,
                metadata_json=goal.metadata,
                created_at=goal.created_at,
                updated_at=goal.updated_at,
                completed_at=goal.completed_at,
                version=goal.version,
            )
        )

    async def update(self, goal: TrainingGoal, *, expected_version: int) -> None:
        statement = (
            update(TrainingGoalModel)
            .where(
                TrainingGoalModel.id == goal.id.value, TrainingGoalModel.version == expected_version
            )
            .values(
                title=goal.title,
                status=goal.status.value,
                priority=goal.priority,
                target_distance_m=goal.target_distance.meters,
                target_duration_seconds=goal.target_duration.seconds,
                target_date=goal.target_date,
                target_pace_seconds_per_100m=goal.target_pace.seconds_per_100m,
                baseline_json=goal.baseline,
                metadata_json=goal.metadata,
                updated_at=goal.updated_at,
                completed_at=goal.completed_at,
                version=goal.version,
            )
            .returning(TrainingGoalModel.version)
        )
        if (await self._session.scalar(statement)) is None:
            raise RevisionConflictError(expected_version)


class SqlAlchemyGoalMilestonesRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list(self, user_id: UserId, goal_id: EntityId) -> Sequence[GoalMilestone]:
        statement = (
            select(GoalMilestoneModel)
            .join(TrainingGoalModel, TrainingGoalModel.id == GoalMilestoneModel.goal_id)
            .where(
                GoalMilestoneModel.goal_id == goal_id.value,
                TrainingGoalModel.user_id == user_id.value,
            )
            .order_by(GoalMilestoneModel.target_date, GoalMilestoneModel.created_at)
        )
        return [
            GoalMilestone(
                id=EntityId(model.id),
                goal_id=EntityId(model.goal_id),
                name=model.name,
                target_date=model.target_date,
                target=_json(model.target_json),
                status=model.status,
                result=_json(model.result_json) if model.result_json else None,
                created_at=model.created_at,
                updated_at=model.updated_at,
                version=model.version,
            )
            for model in await self._session.scalars(statement)
        ]

    async def add(self, milestone: GoalMilestone) -> None:
        self._session.add(
            GoalMilestoneModel(
                id=milestone.id.value,
                goal_id=milestone.goal_id.value,
                name=milestone.name,
                target_date=milestone.target_date,
                target_json=milestone.target,
                status=milestone.status,
                result_json=milestone.result,
                created_at=milestone.created_at,
                updated_at=milestone.updated_at,
                version=milestone.version,
            )
        )


class SqlAlchemyWorkoutsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list(self, user_id: UserId) -> Sequence[PlannedWorkout]:
        statement = (
            select(PlannedWorkoutModel)
            .where(
                PlannedWorkoutModel.user_id == user_id.value,
                PlannedWorkoutModel.status != PlannedWorkoutStatus.DELETING.value,
            )
            .order_by(PlannedWorkoutModel.updated_at.desc())
        )
        return [_workout(model) for model in await self._session.scalars(statement)]

    async def get(self, user_id: UserId, workout_id: EntityId) -> PlannedWorkout | None:
        statement = select(PlannedWorkoutModel).where(
            PlannedWorkoutModel.id == workout_id.value,
            PlannedWorkoutModel.user_id == user_id.value,
        )
        model = (await self._session.scalars(statement)).one_or_none()
        return _workout(model) if model else None

    async def add(self, workout: PlannedWorkout) -> None:
        self._session.add(
            PlannedWorkoutModel(
                id=workout.id.value,
                user_id=workout.user_id.value,
                title=workout.title,
                sport="POOL_SWIMMING",
                purpose=workout.purpose,
                pool_id=workout.pool_id.value,
                status=workout.status.value,
                current_revision_id=(
                    workout.current_revision_id.value if workout.current_revision_id else None
                ),
                approved_revision_id=(
                    workout.approved_revision_id.value if workout.approved_revision_id else None
                ),
                source=workout.source,
                created_at=workout.created_at,
                updated_at=workout.updated_at,
                version=workout.version,
            )
        )

    async def update(self, workout: PlannedWorkout, *, expected_version: int) -> None:
        statement = (
            update(PlannedWorkoutModel)
            .where(
                PlannedWorkoutModel.id == workout.id.value,
                PlannedWorkoutModel.user_id == workout.user_id.value,
                PlannedWorkoutModel.version == expected_version,
            )
            .values(
                title=workout.title,
                purpose=workout.purpose,
                pool_id=workout.pool_id.value,
                status=workout.status.value,
                current_revision_id=(
                    workout.current_revision_id.value if workout.current_revision_id else None
                ),
                approved_revision_id=(
                    workout.approved_revision_id.value if workout.approved_revision_id else None
                ),
                updated_at=workout.updated_at,
                version=workout.version,
            )
            .returning(PlannedWorkoutModel.version)
        )
        if (await self._session.scalar(statement)) is None:
            raise RevisionConflictError(expected_version)

    async def delete(
        self, user_id: UserId, workout_id: EntityId, *, required_status: PlannedWorkoutStatus
    ) -> bool:
        statement = (
            delete(PlannedWorkoutModel)
            .where(
                PlannedWorkoutModel.id == workout_id.value,
                PlannedWorkoutModel.user_id == user_id.value,
                PlannedWorkoutModel.status == required_status.value,
            )
            .returning(PlannedWorkoutModel.id)
        )
        return (await self._session.scalar(statement)) is not None


class SqlAlchemyWorkoutRevisionsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list(self, user_id: UserId, workout_id: EntityId) -> Sequence[WorkoutRevision]:
        statement = (
            select(WorkoutRevisionModel)
            .join(PlannedWorkoutModel, PlannedWorkoutModel.id == WorkoutRevisionModel.workout_id)
            .where(
                WorkoutRevisionModel.workout_id == workout_id.value,
                PlannedWorkoutModel.user_id == user_id.value,
            )
            .order_by(WorkoutRevisionModel.revision_number.desc())
        )
        return [_workout_revision(model) for model in await self._session.scalars(statement)]

    async def get(self, user_id: UserId, revision_id: EntityId) -> WorkoutRevision | None:
        statement = (
            select(WorkoutRevisionModel)
            .join(PlannedWorkoutModel, PlannedWorkoutModel.id == WorkoutRevisionModel.workout_id)
            .where(
                WorkoutRevisionModel.id == revision_id.value,
                PlannedWorkoutModel.user_id == user_id.value,
            )
        )
        model = (await self._session.scalars(statement)).one_or_none()
        return _workout_revision(model) if model else None

    async def list_many(
        self, user_id: UserId, workout_ids: Sequence[EntityId]
    ) -> Sequence[WorkoutRevision]:
        if not workout_ids:
            return []
        statement = (
            select(WorkoutRevisionModel)
            .join(PlannedWorkoutModel, PlannedWorkoutModel.id == WorkoutRevisionModel.workout_id)
            .where(
                WorkoutRevisionModel.workout_id.in_([item.value for item in workout_ids]),
                PlannedWorkoutModel.user_id == user_id.value,
            )
            .order_by(
                WorkoutRevisionModel.workout_id,
                WorkoutRevisionModel.revision_number.desc(),
            )
        )
        return [_workout_revision(model) for model in await self._session.scalars(statement)]

    async def add(self, revision: WorkoutRevision) -> None:
        totals = revision.totals
        self._session.add(
            WorkoutRevisionModel(
                id=revision.id.value,
                workout_id=revision.workout_id.value,
                revision_number=revision.revision_number,
                definition_json=revision.definition.model_dump(mode="json", exclude_none=True),
                total_distance_m=totals.distance_m,
                estimated_active_seconds=Decimal(str(totals.active_seconds)),
                estimated_rest_seconds=Decimal(str(totals.rest_seconds)),
                estimated_total_seconds=Decimal(str(totals.estimated_total_seconds)),
                distance_steps=totals.distance_steps,
                executable_steps=totals.executable_steps,
                lengths=totals.lengths,
                validation_json=revision.validation,
                content_hash=revision.content_hash,
                change_reason=revision.change_reason,
                created_by_type=revision.created_by_type,
                created_by_id=revision.created_by_id,
                created_at=revision.created_at,
            )
        )


class SqlAlchemyWorkoutSchedulesRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: UserId, workout_id: EntityId) -> WorkoutSchedule | None:
        statement = (
            select(WorkoutScheduleModel)
            .join(PlannedWorkoutModel, PlannedWorkoutModel.id == WorkoutScheduleModel.workout_id)
            .where(
                WorkoutScheduleModel.workout_id == workout_id.value,
                PlannedWorkoutModel.user_id == user_id.value,
            )
        )
        model = (await self._session.scalars(statement)).one_or_none()
        return _workout_schedule(model) if model else None

    async def list(
        self, user_id: UserId, workout_ids: Sequence[EntityId]
    ) -> Sequence[WorkoutSchedule]:
        if not workout_ids:
            return []
        statement = (
            select(WorkoutScheduleModel)
            .join(PlannedWorkoutModel, PlannedWorkoutModel.id == WorkoutScheduleModel.workout_id)
            .where(
                WorkoutScheduleModel.workout_id.in_([item.value for item in workout_ids]),
                PlannedWorkoutModel.user_id == user_id.value,
            )
        )
        return [_workout_schedule(model) for model in await self._session.scalars(statement)]

    async def upsert(self, schedule: WorkoutSchedule) -> None:
        statement = insert(WorkoutScheduleModel).values(
            id=schedule.id.value,
            workout_id=schedule.workout_id.value,
            scheduled_date=schedule.scheduled_date,
            scheduled_start_time=schedule.scheduled_start_time,
            timezone=schedule.timezone,
            pool_id=schedule.pool_id.value,
            created_at=schedule.created_at,
            updated_at=schedule.created_at,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[WorkoutScheduleModel.workout_id],
            set_={
                "scheduled_date": schedule.scheduled_date,
                "scheduled_start_time": schedule.scheduled_start_time,
                "timezone": schedule.timezone,
                "pool_id": schedule.pool_id.value,
                "updated_at": schedule.created_at,
            },
        )
        await self._session.execute(statement)

    async def delete(self, user_id: UserId, workout_id: EntityId) -> bool:
        statement = (
            delete(WorkoutScheduleModel)
            .where(
                WorkoutScheduleModel.workout_id == workout_id.value,
                WorkoutScheduleModel.workout_id.in_(
                    select(PlannedWorkoutModel.id).where(
                        PlannedWorkoutModel.user_id == user_id.value
                    )
                ),
            )
            .returning(WorkoutScheduleModel.id)
        )
        return (await self._session.scalar(statement)) is not None


class SqlAlchemyWorkoutTemplatesRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list(self, user_id: UserId) -> Sequence[WorkoutTemplate]:
        statement = (
            select(WorkoutTemplateModel)
            .where(
                WorkoutTemplateModel.active.is_(True),
                or_(
                    WorkoutTemplateModel.owner_user_id.is_(None),
                    WorkoutTemplateModel.owner_user_id == user_id.value,
                ),
            )
            .order_by(WorkoutTemplateModel.is_system.desc(), WorkoutTemplateModel.name)
        )
        return [
            WorkoutTemplate(
                id=EntityId(model.id),
                owner_user_id=UserId(model.owner_user_id) if model.owner_user_id else None,
                name=model.name,
                objective=model.objective,
                tags=tuple(model.tags_json),
                definition=CanonicalWorkout.model_validate(model.definition_json),
                schema_version=model.schema_version,
                is_system=model.is_system,
                active=model.active,
                created_at=model.created_at,
            )
            for model in await self._session.scalars(statement)
        ]

    async def add(self, template: WorkoutTemplate) -> None:
        self._session.add(
            WorkoutTemplateModel(
                id=template.id.value,
                owner_user_id=(template.owner_user_id.value if template.owner_user_id else None),
                name=template.name,
                objective=template.objective,
                tags_json=list(template.tags),
                definition_json=template.definition.model_dump(mode="json", exclude_none=True),
                schema_version=template.schema_version,
                is_system=template.is_system,
                active=template.active,
                created_at=template.created_at,
            )
        )


class SqlAlchemyActionProposalsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: UserId, proposal_id: EntityId) -> ActionProposal | None:
        statement = select(ActionProposalModel).where(
            ActionProposalModel.id == proposal_id.value,
            ActionProposalModel.user_id == user_id.value,
        )
        model = (await self._session.scalars(statement)).one_or_none()
        return _action_proposal(model) if model else None

    async def get_for_update(self, user_id: UserId, proposal_id: EntityId) -> ActionProposal | None:
        statement = (
            select(ActionProposalModel)
            .where(
                ActionProposalModel.id == proposal_id.value,
                ActionProposalModel.user_id == user_id.value,
            )
            .with_for_update()
        )
        model = (await self._session.scalars(statement)).one_or_none()
        return _action_proposal(model) if model else None

    async def get_by_hash(self, user_id: UserId, action_hash: str) -> ActionProposal | None:
        statement = select(ActionProposalModel).where(
            ActionProposalModel.user_id == user_id.value,
            ActionProposalModel.action_hash == action_hash,
        )
        model = (await self._session.scalars(statement)).one_or_none()
        return _action_proposal(model) if model else None

    async def list_recent(self, user_id: UserId, *, limit: int = 50) -> Sequence[ActionProposal]:
        statement = (
            select(ActionProposalModel)
            .where(ActionProposalModel.user_id == user_id.value)
            .order_by(ActionProposalModel.created_at.desc())
            .limit(limit)
        )
        return [_action_proposal(model) for model in await self._session.scalars(statement)]

    async def add(self, proposal: ActionProposal) -> None:
        self._session.add(
            ActionProposalModel(
                id=proposal.id.value,
                user_id=proposal.user_id.value,
                action_type=proposal.action_type,
                target_type=proposal.target_type,
                target_id=proposal.target_id.value,
                target_revision_id=(
                    proposal.target_revision_id.value if proposal.target_revision_id else None
                ),
                payload_json=proposal.payload,
                impact_json=proposal.impact,
                action_hash=proposal.action_hash,
                status=proposal.status.value,
                expires_at=proposal.expires_at,
                created_at=proposal.created_at,
                updated_at=proposal.updated_at,
                version=proposal.version,
            )
        )

    async def update(self, proposal: ActionProposal, *, expected_version: int) -> None:
        statement = (
            update(ActionProposalModel)
            .where(
                ActionProposalModel.id == proposal.id.value,
                ActionProposalModel.user_id == proposal.user_id.value,
                ActionProposalModel.version == expected_version,
            )
            .values(
                status=proposal.status.value,
                updated_at=proposal.updated_at,
                version=proposal.version,
            )
            .returning(ActionProposalModel.version)
        )
        if (await self._session.scalar(statement)) is None:
            raise RevisionConflictError(expected_version)

    async def delete_for_target(
        self, user_id: UserId, target_type: str, target_id: EntityId
    ) -> int:
        statement = (
            delete(ActionProposalModel)
            .where(
                ActionProposalModel.user_id == user_id.value,
                ActionProposalModel.target_type == target_type,
                ActionProposalModel.target_id == target_id.value,
            )
            .returning(ActionProposalModel.id)
        )
        return len((await self._session.scalars(statement)).all())


class SqlAlchemyActionApprovalsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, approval: ActionApproval) -> None:
        self._session.add(
            ActionApprovalModel(
                id=approval.id.value,
                proposal_id=approval.proposal_id.value,
                user_id=approval.user_id.value,
                action_hash=approval.action_hash,
                decision=approval.decision.value,
                explicit_verb=approval.explicit_verb,
                created_at=approval.created_at,
            )
        )


class SqlAlchemyActionExecutionsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_proposal(
        self, user_id: UserId, proposal_id: EntityId
    ) -> ActionExecution | None:
        statement = select(ActionExecutionModel).where(
            ActionExecutionModel.user_id == user_id.value,
            ActionExecutionModel.proposal_id == proposal_id.value,
        )
        model = (await self._session.scalars(statement)).one_or_none()
        return _action_execution(model) if model else None

    async def add(self, execution: ActionExecution) -> None:
        self._session.add(
            ActionExecutionModel(
                id=execution.id.value,
                proposal_id=execution.proposal_id.value,
                user_id=execution.user_id.value,
                idempotency_key=execution.idempotency_key,
                status=execution.status.value,
                result_json=execution.result,
                error_json_redacted=execution.error,
                started_at=execution.started_at,
                finished_at=execution.finished_at,
                created_at=execution.created_at,
                updated_at=execution.updated_at,
                version=execution.version,
            )
        )

    async def update(self, execution: ActionExecution, *, expected_version: int) -> None:
        statement = (
            update(ActionExecutionModel)
            .where(
                ActionExecutionModel.id == execution.id.value,
                ActionExecutionModel.user_id == execution.user_id.value,
                ActionExecutionModel.version == expected_version,
            )
            .values(
                status=execution.status.value,
                result_json=execution.result,
                error_json_redacted=execution.error,
                started_at=execution.started_at,
                finished_at=execution.finished_at,
                updated_at=execution.updated_at,
                version=execution.version,
            )
            .returning(ActionExecutionModel.version)
        )
        if (await self._session.scalar(statement)) is None:
            raise RevisionConflictError(expected_version)


class SqlAlchemyTrainingRuleSetsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_active(self, effective_on: date) -> TrainingRuleSet | None:
        statement = (
            select(TrainingRuleSetModel)
            .where(
                TrainingRuleSetModel.effective_from <= effective_on,
                or_(
                    TrainingRuleSetModel.effective_until.is_(None),
                    TrainingRuleSetModel.effective_until >= effective_on,
                ),
            )
            .order_by(
                TrainingRuleSetModel.effective_from.desc(), TrainingRuleSetModel.version.desc()
            )
            .limit(1)
        )
        model = (await self._session.scalars(statement)).one_or_none()
        return _training_rule_set(model) if model else None

    async def get_by_hash(self, content_hash: str) -> TrainingRuleSet | None:
        statement = select(TrainingRuleSetModel).where(
            TrainingRuleSetModel.content_hash == content_hash
        )
        model = (await self._session.scalars(statement)).one_or_none()
        return _training_rule_set(model) if model else None

    async def add(self, rule_set: TrainingRuleSet) -> None:
        self._session.add(
            TrainingRuleSetModel(
                id=rule_set.id.value,
                name=rule_set.name,
                version=rule_set.version,
                rules_json=rule_set.rules.model_dump(mode="json"),
                schema_version=rule_set.schema_version,
                effective_from=rule_set.effective_from,
                effective_until=rule_set.effective_until,
                content_hash=rule_set.content_hash,
                created_at=rule_set.created_at,
            )
        )


class SqlAlchemyPlanningRunsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_input(
        self, user_id: UserId, rule_set_id: EntityId, input_hash: str
    ) -> PlanningRun | None:
        statement = select(PlanningRunModel).where(
            PlanningRunModel.user_id == user_id.value,
            PlanningRunModel.rule_set_id == rule_set_id.value,
            PlanningRunModel.input_hash == input_hash,
        )
        model = (await self._session.scalars(statement)).one_or_none()
        return _planning_run(model) if model else None

    async def add(self, run: PlanningRun) -> None:
        self._session.add(
            PlanningRunModel(
                id=run.id.value,
                user_id=run.user_id.value,
                goal_id=run.goal_id.value,
                rule_set_id=run.rule_set_id.value,
                week_start=run.week_start,
                input_snapshot_json=run.input_snapshot,
                input_hash=run.input_hash,
                output_plan_json=run.output_plan,
                output_proposal_id=(
                    run.output_proposal_id.value if run.output_proposal_id else None
                ),
                status=run.status.value,
                warnings_json=list(run.warnings),
                created_at=run.created_at,
                completed_at=run.completed_at,
            )
        )


class SqlAlchemyTrainingDecisionsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, decision: TrainingDecisionRecord) -> None:
        self._session.add(
            TrainingDecisionModel(
                id=decision.id.value,
                user_id=decision.user_id.value,
                planning_run_id=decision.planning_run_id.value,
                order_index=decision.order_index,
                decision_type=decision.decision_type,
                rule_id=decision.rule_id,
                effective_date=decision.effective_date,
                evidence_refs_json=list(decision.evidence_refs),
                before_json=decision.before,
                after_json=decision.after,
                rationale=decision.rationale,
                actor_type=decision.actor_type,
                actor_id=decision.actor_id,
                created_at=decision.created_at,
            )
        )

    async def list_for_run(
        self, user_id: UserId, planning_run_id: EntityId
    ) -> Sequence[TrainingDecisionRecord]:
        statement = (
            select(TrainingDecisionModel)
            .where(
                TrainingDecisionModel.user_id == user_id.value,
                TrainingDecisionModel.planning_run_id == planning_run_id.value,
            )
            .order_by(TrainingDecisionModel.order_index)
        )
        return [_training_decision(model) for model in await self._session.scalars(statement)]


class SqlAlchemyExternalWorkoutBindingsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: UserId, binding_id: EntityId) -> ExternalWorkoutBinding | None:
        statement = select(ExternalWorkoutBindingModel).where(
            ExternalWorkoutBindingModel.id == binding_id.value,
            ExternalWorkoutBindingModel.user_id == user_id.value,
        )
        model = (await self._session.scalars(statement)).one_or_none()
        return _external_workout_binding(model) if model else None

    async def get_by_revision_hash(
        self,
        user_id: UserId,
        provider: str,
        revision_id: EntityId,
        compiled_hash: str,
    ) -> ExternalWorkoutBinding | None:
        statement = select(ExternalWorkoutBindingModel).where(
            ExternalWorkoutBindingModel.user_id == user_id.value,
            ExternalWorkoutBindingModel.provider == provider,
            ExternalWorkoutBindingModel.revision_id == revision_id.value,
            ExternalWorkoutBindingModel.compiled_hash == compiled_hash,
        )
        model = (await self._session.scalars(statement)).one_or_none()
        return _external_workout_binding(model) if model else None

    async def get_by_workout(
        self, user_id: UserId, provider: str, workout_id: EntityId
    ) -> ExternalWorkoutBinding | None:
        statement = (
            select(ExternalWorkoutBindingModel)
            .where(
                ExternalWorkoutBindingModel.user_id == user_id.value,
                ExternalWorkoutBindingModel.provider == provider,
                ExternalWorkoutBindingModel.workout_id == workout_id.value,
            )
            .order_by(ExternalWorkoutBindingModel.updated_at.desc())
            .limit(1)
        )
        model = (await self._session.scalars(statement)).one_or_none()
        return _external_workout_binding(model) if model else None

    async def add(self, binding: ExternalWorkoutBinding) -> None:
        self._session.add(
            ExternalWorkoutBindingModel(
                id=binding.id.value,
                user_id=binding.user_id.value,
                workout_id=binding.workout_id.value,
                revision_id=binding.revision_id.value,
                provider=binding.provider,
                compiled_hash=binding.compiled_hash,
                status=binding.status.value,
                external_workout_id=binding.external_workout_id,
                external_schedule_id=binding.external_schedule_id,
                scheduled_date=binding.scheduled_date,
                last_error_json_redacted=binding.last_error,
                created_at=binding.created_at,
                updated_at=binding.updated_at,
                version=binding.version,
            )
        )

    async def update(self, binding: ExternalWorkoutBinding, *, expected_version: int) -> None:
        statement = (
            update(ExternalWorkoutBindingModel)
            .where(
                ExternalWorkoutBindingModel.id == binding.id.value,
                ExternalWorkoutBindingModel.user_id == binding.user_id.value,
                ExternalWorkoutBindingModel.version == expected_version,
            )
            .values(
                workout_id=binding.workout_id.value,
                revision_id=binding.revision_id.value,
                provider=binding.provider,
                compiled_hash=binding.compiled_hash,
                status=binding.status.value,
                external_workout_id=binding.external_workout_id,
                external_schedule_id=binding.external_schedule_id,
                scheduled_date=binding.scheduled_date,
                last_error_json_redacted=binding.last_error,
                updated_at=binding.updated_at,
                version=binding.version,
            )
            .returning(ExternalWorkoutBindingModel.version)
        )
        if (await self._session.scalar(statement)) is None:
            raise RevisionConflictError(expected_version)


class SqlAlchemyJobsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, job: Job) -> None:
        self._session.add(
            JobModel(
                id=job.id.value,
                user_id=job.user_id.value if job.user_id else None,
                job_type=job.job_type,
                payload_json=job.payload,
                status=job.status.value,
                priority=job.priority,
                available_at=job.available_at,
                attempts=job.attempts,
                max_attempts=job.max_attempts,
                idempotency_key=job.idempotency_key,
                locked_by=job.locked_by,
                locked_at=job.locked_at,
                heartbeat_at=job.heartbeat_at,
                lease_expires_at=job.lease_expires_at,
                last_error_json_redacted=job.last_error,
                created_at=job.created_at,
                updated_at=job.updated_at,
                finished_at=job.finished_at,
                version=job.version,
            )
        )

    async def get(self, user_id: UserId, job_id: EntityId) -> Job | None:
        statement = select(JobModel).where(
            JobModel.id == job_id.value,
            JobModel.user_id == user_id.value,
        )
        model = (await self._session.scalars(statement)).one_or_none()
        return _job(model) if model else None

    async def get_by_idempotency_key(self, idempotency_key: str) -> Job | None:
        statement = select(JobModel).where(JobModel.idempotency_key == idempotency_key)
        model = (await self._session.scalars(statement)).one_or_none()
        return _job(model) if model else None

    async def retry_failed(self, user_id: UserId, job_id: EntityId, at: datetime) -> Job | None:
        statement = (
            update(JobModel)
            .where(
                JobModel.id == job_id.value,
                JobModel.user_id == user_id.value,
                JobModel.status == JobStatus.FAILED_TERMINAL.value,
            )
            .values(
                status=JobStatus.RETRY_SCHEDULED.value,
                available_at=at,
                finished_at=None,
                locked_by=None,
                locked_at=None,
                heartbeat_at=None,
                lease_expires_at=None,
                updated_at=at,
                version=JobModel.version + 1,
            )
            .returning(JobModel.id)
        )
        if await self._session.scalar(statement) is None:
            return None
        return await self.get(user_id, job_id)

    async def add_idempotent(self, job: Job) -> Job:
        if job.idempotency_key is None:
            raise ValueError("idempotent job requires an idempotency key")
        statement = (
            insert(JobModel)
            .values(
                id=job.id.value,
                user_id=job.user_id.value if job.user_id else None,
                job_type=job.job_type,
                payload_json=job.payload,
                status=job.status.value,
                priority=job.priority,
                available_at=job.available_at,
                attempts=job.attempts,
                max_attempts=job.max_attempts,
                idempotency_key=job.idempotency_key,
                locked_by=job.locked_by,
                locked_at=job.locked_at,
                heartbeat_at=job.heartbeat_at,
                lease_expires_at=job.lease_expires_at,
                last_error_json_redacted=job.last_error,
                created_at=job.created_at,
                updated_at=job.updated_at,
                finished_at=job.finished_at,
                version=job.version,
            )
            .on_conflict_do_nothing(index_elements=[JobModel.idempotency_key])
            .returning(JobModel.id)
        )
        inserted_id = await self._session.scalar(statement)
        if inserted_id is not None:
            return job
        existing = await self.get_by_idempotency_key(job.idempotency_key)
        if existing is None:
            raise RuntimeError("idempotent job conflict could not be resolved")
        return existing

    async def lease_next(
        self, worker_id: str, *, ttl: timedelta, job_types: frozenset[str]
    ) -> Job | None:
        if not job_types:
            return None
        from datetime import UTC

        now = datetime.now(UTC)
        statement = (
            select(JobModel)
            .where(
                JobModel.job_type.in_(job_types),
                or_(
                    JobModel.status.in_([JobStatus.QUEUED.value, JobStatus.RETRY_SCHEDULED.value]),
                    and_(
                        JobModel.status == JobStatus.LEASED.value,
                        JobModel.lease_expires_at <= now,
                    ),
                ),
                JobModel.available_at <= now,
            )
            .order_by(JobModel.priority.desc(), JobModel.available_at, JobModel.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        model = (await self._session.scalars(statement)).one_or_none()
        if model is None:
            return None
        job = _job(model)
        if job.status is JobStatus.LEASED:
            job.status = JobStatus.QUEUED
        job.lease(worker_id, ttl=ttl)
        model.status = job.status.value
        model.locked_by = job.locked_by
        model.locked_at = job.locked_at
        model.heartbeat_at = job.heartbeat_at
        model.lease_expires_at = job.lease_expires_at
        model.attempts = job.attempts
        model.updated_at = job.updated_at
        model.version = job.version
        await self._session.flush()
        return job

    async def mark_succeeded(self, job_id: EntityId, worker_id: str, at: datetime) -> bool:
        statement = (
            update(JobModel)
            .where(
                JobModel.id == job_id.value,
                JobModel.status == JobStatus.LEASED.value,
                JobModel.locked_by == worker_id,
            )
            .values(
                status=JobStatus.SUCCEEDED.value,
                finished_at=at,
                updated_at=at,
                locked_by=None,
                locked_at=None,
                heartbeat_at=None,
                lease_expires_at=None,
                version=JobModel.version + 1,
            )
            .returning(JobModel.id)
        )
        return (await self._session.scalar(statement)) is not None

    async def mark_failed(
        self,
        job_id: EntityId,
        worker_id: str,
        at: datetime,
        *,
        error: JsonObject,
        retry_at: datetime | None,
    ) -> bool:
        values: dict[str, Any] = {
            "status": (
                JobStatus.RETRY_SCHEDULED.value
                if retry_at is not None
                else JobStatus.FAILED_TERMINAL.value
            ),
            "updated_at": at,
            "finished_at": None if retry_at is not None else at,
            "last_error_json_redacted": error,
            "locked_by": None,
            "locked_at": None,
            "heartbeat_at": None,
            "lease_expires_at": None,
            "version": JobModel.version + 1,
        }
        if retry_at is not None:
            values["available_at"] = retry_at
        statement = (
            update(JobModel)
            .where(
                JobModel.id == job_id.value,
                JobModel.status == JobStatus.LEASED.value,
                JobModel.locked_by == worker_id,
            )
            .values(**values)
            .returning(JobModel.id)
        )
        return (await self._session.scalar(statement)) is not None

    async def mark_needs_reconciliation(
        self, job_id: EntityId, worker_id: str, at: datetime, *, error: JsonObject
    ) -> bool:
        statement = (
            update(JobModel)
            .where(
                JobModel.id == job_id.value,
                JobModel.status == JobStatus.LEASED.value,
                JobModel.locked_by == worker_id,
            )
            .values(
                status=JobStatus.NEEDS_RECONCILIATION.value,
                finished_at=at,
                updated_at=at,
                last_error_json_redacted=error,
                locked_by=None,
                locked_at=None,
                heartbeat_at=None,
                lease_expires_at=None,
                version=JobModel.version + 1,
            )
            .returning(JobModel.id)
        )
        return (await self._session.scalar(statement)) is not None

    async def list_recent(self, user_id: UserId, *, limit: int = 50) -> Sequence[Job]:
        statement = (
            select(JobModel)
            .where(JobModel.user_id == user_id.value)
            .order_by(JobModel.created_at.desc())
            .limit(limit)
        )
        return [_job(model) for model in await self._session.scalars(statement)]

    async def metrics(self, user_id: UserId, now: datetime) -> JsonObject:
        statement = select(JobModel).where(JobModel.user_id == user_id.value)
        models = list(await self._session.scalars(statement))
        counts: dict[str, int] = {}
        active_created: list[datetime] = []
        active = {JobStatus.QUEUED.value, JobStatus.RETRY_SCHEDULED.value, JobStatus.LEASED.value}
        for model in models:
            counts[model.status] = counts.get(model.status, 0) + 1
            if model.status in active:
                active_created.append(model.created_at)
        oldest_age = (
            max(0, int((now - min(active_created)).total_seconds())) if active_created else 0
        )
        return cast(
            JsonObject,
            {
                "counts": counts,
                "oldest_active_age_seconds": oldest_age,
                "dead_count": counts.get(JobStatus.FAILED_TERMINAL.value, 0)
                + counts.get(JobStatus.NEEDS_RECONCILIATION.value, 0),
            },
        )

    async def purge_finished(self, before: datetime) -> int:
        statement = (
            delete(JobModel)
            .where(JobModel.finished_at.is_not(None), JobModel.finished_at < before)
            .returning(JobModel.id)
        )
        result = await self._session.execute(statement)
        return len(result.scalars().all())


class SqlAlchemyNotificationsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_idempotent(self, notification: Notification) -> Notification:
        statement = (
            insert(NotificationModel)
            .values(
                id=notification.id.value,
                user_id=notification.user_id.value,
                notification_type=notification.notification_type,
                dedupe_key=notification.dedupe_key,
                title=notification.title,
                body=notification.body,
                link=notification.link,
                read_at=notification.read_at,
                created_at=notification.created_at,
            )
            .on_conflict_do_nothing(constraint="uq_notification_user_dedupe")
            .returning(NotificationModel.id)
        )
        if await self._session.scalar(statement) is not None:
            return notification
        existing = (
            await self._session.scalars(
                select(NotificationModel).where(
                    NotificationModel.user_id == notification.user_id.value,
                    NotificationModel.dedupe_key == notification.dedupe_key,
                )
            )
        ).one()
        return _notification(existing)

    async def list_recent(self, user_id: UserId, *, limit: int = 50) -> Sequence[Notification]:
        statement = (
            select(NotificationModel)
            .where(NotificationModel.user_id == user_id.value)
            .order_by(NotificationModel.created_at.desc())
            .limit(limit)
        )
        return [_notification(model) for model in await self._session.scalars(statement)]

    async def mark_read(
        self, user_id: UserId, notification_id: EntityId, at: datetime
    ) -> Notification | None:
        statement = (
            update(NotificationModel)
            .where(
                NotificationModel.id == notification_id.value,
                NotificationModel.user_id == user_id.value,
            )
            .values(read_at=at)
            .returning(NotificationModel)
        )
        model = (await self._session.scalars(statement)).one_or_none()
        return _notification(model) if model is not None else None


class SqlAlchemyPrivacyRequestsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_export(self, data_export: DataExport) -> None:
        self._session.add(
            DataExportModel(
                id=data_export.id.value,
                user_id=data_export.user_id.value,
                status=data_export.status.value,
                storage_key=data_export.storage_key,
                checksum=data_export.checksum,
                size_bytes=data_export.size_bytes,
                created_at=data_export.created_at,
                completed_at=data_export.completed_at,
                expires_at=data_export.expires_at,
            )
        )

    async def get_export(self, user_id: UserId, export_id: EntityId) -> DataExport | None:
        statement = select(DataExportModel).where(
            DataExportModel.id == export_id.value,
            DataExportModel.user_id == user_id.value,
        )
        model = (await self._session.scalars(statement)).one_or_none()
        return _data_export(model) if model else None

    async def update_export(self, data_export: DataExport) -> None:
        statement = (
            update(DataExportModel)
            .where(
                DataExportModel.id == data_export.id.value,
                DataExportModel.user_id == data_export.user_id.value,
            )
            .values(
                status=data_export.status.value,
                storage_key=data_export.storage_key,
                checksum=data_export.checksum,
                size_bytes=data_export.size_bytes,
                completed_at=data_export.completed_at,
                expires_at=data_export.expires_at,
            )
            .returning(DataExportModel.id)
        )
        if await self._session.scalar(statement) is None:
            raise RevisionConflictError(1)

    async def list_export_keys(self, user_id: UserId) -> Sequence[str]:
        statement = select(DataExportModel.storage_key).where(
            DataExportModel.user_id == user_id.value,
            DataExportModel.storage_key.is_not(None),
        )
        return [item for item in await self._session.scalars(statement) if item is not None]

    async def add_deletion(self, request: DeletionRequest) -> None:
        self._session.add(
            DeletionRequestModel(
                id=request.id.value,
                user_id=request.user_id.value if request.user_id else None,
                status=request.status.value,
                execute_after=request.execute_after,
                created_at=request.created_at,
                executed_at=request.executed_at,
            )
        )

    async def get_deletion(self, user_id: UserId, request_id: EntityId) -> DeletionRequest | None:
        statement = select(DeletionRequestModel).where(
            DeletionRequestModel.id == request_id.value,
            DeletionRequestModel.user_id == user_id.value,
        )
        model = (await self._session.scalars(statement)).one_or_none()
        return _deletion_request(model) if model else None

    async def update_deletion(self, request: DeletionRequest) -> None:
        statement = (
            update(DeletionRequestModel)
            .where(DeletionRequestModel.id == request.id.value)
            .values(
                user_id=request.user_id.value if request.user_id else None,
                status=request.status.value,
                executed_at=request.executed_at,
            )
            .returning(DeletionRequestModel.id)
        )
        if await self._session.scalar(statement) is None:
            raise RevisionConflictError(1)

    async def stage_user_deletion(self, user_id: UserId, at: datetime) -> None:
        await self._session.execute(
            update(AppUserModel)
            .where(AppUserModel.id == user_id.value)
            .values(
                status=UserStatus.DISABLED.value, updated_at=at, version=AppUserModel.version + 1
            )
        )
        await self._session.execute(
            update(WebSessionModel)
            .where(WebSessionModel.user_id == user_id.value, WebSessionModel.revoked_at.is_(None))
            .values(revoked_at=at)
        )
        await self._session.execute(
            update(GarminConnectionModel)
            .where(GarminConnectionModel.user_id == user_id.value)
            .values(
                status=GarminConnectionStatus.DISABLED.value,
                encrypted_token_bundle=None,
                token_nonce=None,
                token_key_version=None,
                updated_at=at,
                version=GarminConnectionModel.version + 1,
            )
        )
        await self._session.execute(
            update(JobModel)
            .where(
                JobModel.user_id == user_id.value,
                JobModel.status.in_(
                    [
                        JobStatus.QUEUED.value,
                        JobStatus.RETRY_SCHEDULED.value,
                        JobStatus.LEASED.value,
                        JobStatus.RUNNING.value,
                    ]
                ),
            )
            .values(
                status=JobStatus.FAILED_TERMINAL.value,
                finished_at=at,
                updated_at=at,
                locked_by=None,
                locked_at=None,
                heartbeat_at=None,
                lease_expires_at=None,
                last_error_json_redacted={"code": "DELETION_REQUESTED", "retryable": False},
                version=JobModel.version + 1,
            )
        )
        await self._session.execute(
            update(ActionProposalModel)
            .where(
                ActionProposalModel.user_id == user_id.value,
                ActionProposalModel.status.in_(
                    [
                        ActionProposalStatus.DRAFT.value,
                        ActionProposalStatus.READY_FOR_REVIEW.value,
                        ActionProposalStatus.APPROVED.value,
                        ActionProposalStatus.QUEUED.value,
                    ]
                ),
            )
            .values(
                status=ActionProposalStatus.CANCELLED.value,
                updated_at=at,
                version=ActionProposalModel.version + 1,
            )
        )

    async def delete_user(self, user_id: UserId) -> bool:
        statement = (
            delete(AppUserModel).where(AppUserModel.id == user_id.value).returning(AppUserModel.id)
        )
        return (await self._session.scalar(statement)) is not None


class SqlAlchemyOutboxRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, event: OutboxEvent) -> None:
        self._session.add(
            OutboxEventModel(
                id=event.id.value,
                aggregate_type=event.aggregate_type,
                aggregate_id=event.aggregate_id.value,
                aggregate_version=event.aggregate_version,
                event_type=event.event_type,
                payload_json=event.payload,
                user_id=event.user_id.value if event.user_id else None,
                correlation_id=event.correlation_id.value,
                causation_id=event.causation_id.value if event.causation_id else None,
                occurred_at=event.occurred_at,
                published_at=event.published_at,
                attempts=event.attempts,
                last_error=event.last_error,
            )
        )


class SqlAlchemyAuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, event: AuditEvent) -> None:
        self._session.add(
            AuditEventModel(
                id=event.id.value,
                user_id=event.user_id.value if event.user_id else None,
                actor_type=event.actor_type,
                actor_id=event.actor_id,
                action=event.action,
                entity_type=event.entity_type,
                entity_id=event.entity_id.value if event.entity_id else None,
                before_json_redacted=event.before,
                after_json_redacted=event.after,
                correlation_id=event.correlation_id.value,
                ip_hash=event.ip_hash,
                user_agent_summary=event.user_agent_summary,
                created_at=event.created_at,
            )
        )


class SqlAlchemyMcpToolInvocationsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, invocation: McpToolInvocation) -> None:
        self._session.add(
            McpToolInvocationModel(
                id=invocation.id.value,
                user_id=invocation.user_id.value,
                tool_name=invocation.tool_name,
                request_id=invocation.request_id,
                args_hash=invocation.args_hash,
                outcome=invocation.outcome,
                latency_ms=invocation.latency_ms,
                correlation_id=(
                    invocation.correlation_id.value if invocation.correlation_id else None
                ),
                causation_id=invocation.causation_id.value if invocation.causation_id else None,
                error_code=invocation.error_code,
                created_at=invocation.created_at,
            )
        )


class SqlAlchemyIdempotencyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, scope: str, key: str, now: datetime) -> ApiIdempotencyRecord | None:
        statement = select(ApiIdempotencyRecordModel).where(
            ApiIdempotencyRecordModel.scope == scope,
            ApiIdempotencyRecordModel.idempotency_key == key,
            ApiIdempotencyRecordModel.expires_at > now,
        )
        model = (await self._session.scalars(statement)).one_or_none()
        if model is None:
            return None
        return ApiIdempotencyRecord(
            scope=model.scope,
            idempotency_key=model.idempotency_key,
            request_hash=model.request_hash,
            response_status=model.response_status,
            response=_json(model.response_json),
            created_at=model.created_at,
            expires_at=model.expires_at,
        )

    async def add(self, record: ApiIdempotencyRecord) -> None:
        self._session.add(
            ApiIdempotencyRecordModel(
                scope=record.scope,
                idempotency_key=record.idempotency_key,
                request_hash=record.request_hash,
                response_status=record.response_status,
                response_json=record.response,
                created_at=record.created_at,
                expires_at=record.expires_at,
            )
        )


class SqlAlchemySessionsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, session: WebSession) -> None:
        self._session.add(
            WebSessionModel(
                id=session.id.value,
                user_id=session.user_id.value,
                token_hash=session.token_hash,
                csrf_hash=session.csrf_hash,
                expires_at=session.expires_at,
                created_at=session.created_at,
                last_seen_at=session.last_seen_at,
                revoked_at=session.revoked_at,
            )
        )

    async def get_active_by_token_hash(self, token_hash: str, now: datetime) -> WebSession | None:
        statement = select(WebSessionModel).where(
            WebSessionModel.token_hash == token_hash,
            WebSessionModel.revoked_at.is_(None),
            WebSessionModel.expires_at > now,
        )
        model = (await self._session.scalars(statement)).one_or_none()
        if model is None:
            return None
        return WebSession(
            id=EntityId(model.id),
            user_id=UserId(model.user_id),
            token_hash=model.token_hash,
            csrf_hash=model.csrf_hash,
            expires_at=model.expires_at,
            created_at=model.created_at,
            last_seen_at=model.last_seen_at,
            revoked_at=model.revoked_at,
        )

    async def revoke(self, session_id: EntityId, at: datetime) -> None:
        await self._session.execute(
            update(WebSessionModel)
            .where(WebSessionModel.id == session_id.value, WebSessionModel.revoked_at.is_(None))
            .values(revoked_at=at)
        )


class SqlAlchemyOidcLoginAttemptsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, attempt: OidcLoginAttempt) -> None:
        self._session.add(
            OidcLoginAttemptModel(
                id=attempt.id.value,
                state_hash=attempt.state_hash,
                code_verifier=attempt.code_verifier,
                nonce=attempt.nonce,
                redirect_uri=attempt.redirect_uri,
                expires_at=attempt.expires_at,
                created_at=attempt.created_at,
                consumed_at=attempt.consumed_at,
            )
        )

    async def consume(self, state_hash: str, now: datetime) -> OidcLoginAttempt | None:
        statement = (
            select(OidcLoginAttemptModel)
            .where(
                OidcLoginAttemptModel.state_hash == state_hash,
                OidcLoginAttemptModel.consumed_at.is_(None),
                OidcLoginAttemptModel.expires_at > now,
            )
            .with_for_update()
        )
        model = (await self._session.scalars(statement)).one_or_none()
        if model is None:
            return None
        model.consumed_at = now
        await self._session.flush()
        return OidcLoginAttempt(
            id=EntityId(model.id),
            state_hash=model.state_hash,
            code_verifier=model.code_verifier,
            nonce=model.nonce,
            redirect_uri=model.redirect_uri,
            expires_at=model.expires_at,
            created_at=model.created_at,
            consumed_at=model.consumed_at,
        )


class SqlAlchemyUnitOfWork:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None

    async def __aenter__(self) -> Self:
        self._session = self._session_factory()
        self.users = SqlAlchemyUsersRepository(self._session)
        self.identities = SqlAlchemyIdentitiesRepository(self._session)
        self.profiles = SqlAlchemyProfilesRepository(self._session)
        self.pools = SqlAlchemyPoolsRepository(self._session)
        self.availability = SqlAlchemyAvailabilityRepository(self._session)
        self.constraints = SqlAlchemyConstraintsRepository(self._session)
        self.devices = SqlAlchemyDevicesRepository(self._session)
        self.garmin_connections = SqlAlchemyGarminConnectionsRepository(self._session)
        self.sync_cursors = SqlAlchemySyncCursorsRepository(self._session)
        self.sync_runs = SqlAlchemySyncRunsRepository(self._session)
        self.raw_provider_payloads = SqlAlchemyRawProviderPayloadsRepository(self._session)
        self.activities = SqlAlchemyActivitiesRepository(self._session)
        self.activity_data = SqlAlchemyActivityDataRepository(self._session)
        self.activity_imports = SqlAlchemyActivityImportsRepository(self._session)
        self.goals = SqlAlchemyGoalsRepository(self._session)
        self.goal_milestones = SqlAlchemyGoalMilestonesRepository(self._session)
        self.workouts = SqlAlchemyWorkoutsRepository(self._session)
        self.workout_revisions = SqlAlchemyWorkoutRevisionsRepository(self._session)
        self.workout_schedules = SqlAlchemyWorkoutSchedulesRepository(self._session)
        self.workout_templates = SqlAlchemyWorkoutTemplatesRepository(self._session)
        self.action_proposals = SqlAlchemyActionProposalsRepository(self._session)
        self.action_approvals = SqlAlchemyActionApprovalsRepository(self._session)
        self.action_executions = SqlAlchemyActionExecutionsRepository(self._session)
        self.training_rule_sets = SqlAlchemyTrainingRuleSetsRepository(self._session)
        self.planning_runs = SqlAlchemyPlanningRunsRepository(self._session)
        self.training_decisions = SqlAlchemyTrainingDecisionsRepository(self._session)
        self.external_workout_bindings = SqlAlchemyExternalWorkoutBindingsRepository(self._session)
        self.jobs = SqlAlchemyJobsRepository(self._session)
        self.notifications = SqlAlchemyNotificationsRepository(self._session)
        self.privacy_requests = SqlAlchemyPrivacyRequestsRepository(self._session)
        self.outbox = SqlAlchemyOutboxRepository(self._session)
        self.audit = SqlAlchemyAuditRepository(self._session)
        self.mcp_tool_invocations = SqlAlchemyMcpToolInvocationsRepository(self._session)
        self.idempotency = SqlAlchemyIdempotencyRepository(self._session)
        self.sessions = SqlAlchemySessionsRepository(self._session)
        self.oidc_login_attempts = SqlAlchemyOidcLoginAttemptsRepository(self._session)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._session is None:
            return
        if exc_type is not None:
            await self._session.rollback()
        await self._session.close()

    async def commit(self) -> None:
        if self._session is None:
            raise RuntimeError("unit of work has not been entered")
        await self._session.commit()

    async def flush(self) -> None:
        if self._session is None:
            raise RuntimeError("unit of work has not been entered")
        await self._session.flush()

    async def rollback(self) -> None:
        if self._session is None:
            raise RuntimeError("unit of work has not been entered")
        await self._session.rollback()


class SqlAlchemyUnitOfWorkFactory:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    def __call__(self) -> UnitOfWork:
        return SqlAlchemyUnitOfWork(self._session_factory)
