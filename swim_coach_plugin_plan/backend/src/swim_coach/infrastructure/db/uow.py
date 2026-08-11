"""SQLAlchemy repositories and unit-of-work adapter."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from decimal import Decimal
from types import TracebackType
from typing import Any, Self, cast

from sqlalchemy import and_, delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from swim_coach.application.ports.repositories import UnitOfWork
from swim_coach.domain.athlete import (
    AthleteConstraint,
    AthleteProfile,
    AvailabilityRule,
    ConstraintType,
    Device,
    Pool,
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
    EntityId,
    Pace,
    PoolLength,
    UserId,
)
from swim_coach.infrastructure.db.models import (
    ApiIdempotencyRecordModel,
    AppUserModel,
    AthleteConstraintModel,
    AthleteProfileModel,
    AuditEventModel,
    AuthIdentityModel,
    AvailabilityRuleModel,
    DeviceModel,
    GoalMilestoneModel,
    JobModel,
    OidcLoginAttemptModel,
    OutboxEventModel,
    PoolModel,
    TrainingGoalModel,
    WebSessionModel,
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
        self.goals = SqlAlchemyGoalsRepository(self._session)
        self.goal_milestones = SqlAlchemyGoalMilestonesRepository(self._session)
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
