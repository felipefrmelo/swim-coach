"""SQLAlchemy repositories and unit-of-work adapter."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from decimal import Decimal
from types import TracebackType
from typing import Any, Self, cast

from sqlalchemy import and_, delete, or_, select, update
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
    Job,
    JobStatus,
    OutboxEvent,
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
    ActivityImportModel,
    ActivityModel,
    ApiIdempotencyRecordModel,
    AppUserModel,
    AthleteConstraintModel,
    AthleteProfileModel,
    AuditEventModel,
    AuthIdentityModel,
    AvailabilityRuleModel,
    DeviceModel,
    ExternalWorkoutBindingModel,
    GarminConnectionModel,
    GoalMilestoneModel,
    JobModel,
    OidcLoginAttemptModel,
    OutboxEventModel,
    PlannedWorkoutModel,
    PoolModel,
    RawProviderPayloadModel,
    SyncCursorModel,
    SyncRunModel,
    TrainingGoalModel,
    WebSessionModel,
    WorkoutRevisionModel,
    WorkoutScheduleModel,
    WorkoutTemplateModel,
)


def _json(value: dict[str, Any]) -> JsonObject:
    return cast(JsonObject, value)


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


def _action_proposal(model: ActionProposalModel) -> ActionProposal:
    return ActionProposal(
        id=EntityId(model.id),
        user_id=UserId(model.user_id),
        action_type=model.action_type,
        target_type=model.target_type,
        target_id=EntityId(model.target_id),
        target_revision_id=EntityId(model.target_revision_id),
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
        if model is not None and model.summary_checksum == activity.summary_checksum:
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

    async def list_recent(self, user_id: UserId, *, limit: int = 50) -> Sequence[Activity]:
        statement = (
            select(ActivityModel)
            .where(ActivityModel.user_id == user_id.value)
            .order_by(ActivityModel.start_time_utc.desc())
            .limit(limit)
        )
        return [_activity(model) for model in await self._session.scalars(statement)]


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
            .where(PlannedWorkoutModel.user_id == user_id.value)
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
        if not model:
            return None
        return WorkoutSchedule(
            id=EntityId(model.id),
            workout_id=EntityId(model.workout_id),
            scheduled_date=model.scheduled_date,
            scheduled_start_time=model.scheduled_start_time,
            timezone=model.timezone,
            pool_id=EntityId(model.pool_id),
            created_at=model.created_at,
        )

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
                target_revision_id=proposal.target_revision_id.value,
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

    async def get_by_idempotency_key(self, idempotency_key: str) -> Job | None:
        statement = select(JobModel).where(JobModel.idempotency_key == idempotency_key)
        model = (await self._session.scalars(statement)).one_or_none()
        return _job(model) if model else None

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
        self.external_workout_bindings = SqlAlchemyExternalWorkoutBindingsRepository(self._session)
        self.jobs = SqlAlchemyJobsRepository(self._session)
        self.outbox = SqlAlchemyOutboxRepository(self._session)
        self.audit = SqlAlchemyAuditRepository(self._session)
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
