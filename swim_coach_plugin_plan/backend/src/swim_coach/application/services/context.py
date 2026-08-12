"""User-scoped profile, pool, availability and goal use cases."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from swim_coach.application.ports.repositories import UnitOfWork, UnitOfWorkFactory
from swim_coach.domain.athlete import AthleteProfile, AvailabilityRule, Pool
from swim_coach.domain.goals import GoalStatus, TrainingGoal
from swim_coach.domain.identity import AppUser
from swim_coach.domain.operations import ApiIdempotencyRecord, AuditEvent, OutboxEvent
from swim_coach.domain.shared.errors import (
    DomainError,
    ResourceNotFoundError,
    RevisionConflictError,
)
from swim_coach.domain.shared.value_objects import (
    CorrelationId,
    Distance,
    Duration,
    EntityId,
    IdempotencyKey,
    PoolLength,
    UserId,
)


@dataclass(frozen=True, slots=True)
class MeContext:
    user: AppUser
    profile: AthleteProfile


@dataclass(frozen=True, slots=True)
class AvailabilityInput:
    day_of_week: int
    start_local_time: time
    end_local_time: time
    max_duration_minutes: int
    pool_id: EntityId | None = None
    valid_from: date | None = None
    valid_until: date | None = None
    priority: int = 0


class ContextService:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def get_me(self, user_id: UserId) -> MeContext:
        async with self._uow_factory() as uow:
            user = await uow.users.get(user_id)
            profile = await uow.profiles.get(user_id)
            if user is None or profile is None:
                raise ResourceNotFoundError("profile")
            return MeContext(user=user, profile=profile)

    async def update_profile(
        self,
        user_id: UserId,
        *,
        display_name: str,
        locale: str,
        timezone: str,
        experience_level: str,
        default_sessions_per_week: int,
        expected_version: int,
        correlation_id: CorrelationId,
    ) -> MeContext:
        async with self._uow_factory() as uow:
            user = await uow.users.get(user_id)
            profile = await uow.profiles.get(user_id)
            if user is None or profile is None:
                raise ResourceNotFoundError("profile")
            previous_user_version = user.version
            previous_profile_version = profile.version
            if expected_version != profile.version:
                raise RevisionConflictError(profile.version)
            user.display_name = display_name.strip()
            user.locale = locale
            user.timezone = timezone
            user.updated_at = datetime.now(UTC)
            user.version += 1
            profile.experience_level = experience_level
            profile.default_sessions_per_week = default_sessions_per_week
            profile.updated_at = datetime.now(UTC)
            profile.version += 1
            user.__post_init__()
            profile.__post_init__()
            await uow.users.update(user, expected_version=previous_user_version)
            await uow.profiles.update(profile, expected_version=previous_profile_version)
            await self._record_change(
                uow,
                user_id=user_id,
                aggregate_type="AthleteProfile",
                aggregate_id=EntityId(user_id.value),
                event_type="swim_coach.athlete.profile_updated.v1",
                action="athlete.profile_updated",
                payload={"profile_version": profile.version},
                correlation_id=correlation_id,
            )
            await uow.commit()
            return MeContext(user=user, profile=profile)

    async def list_pools(self, user_id: UserId) -> Sequence[Pool]:
        async with self._uow_factory() as uow:
            return await uow.pools.list(user_id)

    async def create_pool(
        self,
        user_id: UserId,
        *,
        name: str,
        length_m: int,
        is_default: bool,
        location_label: str | None,
        correlation_id: CorrelationId,
        idempotency_key: IdempotencyKey | None = None,
        request_hash: str | None = None,
    ) -> Pool:
        pool = Pool(
            id=EntityId.new(),
            user_id=user_id,
            name=name,
            length=PoolLength(length_m),
            is_default=is_default,
            location_label=location_label,
        )
        async with self._uow_factory() as uow:
            if idempotency_key is not None:
                existing = await self._replay_idempotent(
                    uow,
                    scope=f"{user_id}:pools:create",
                    key=idempotency_key,
                    request_hash=request_hash,
                )
                if existing is not None:
                    resource_id = existing.response.get("resource_id")
                    if not isinstance(resource_id, str):
                        raise DomainError(
                            "INTERNAL_ERROR", "Stored idempotency response is invalid."
                        )
                    replayed = await uow.pools.get(user_id, EntityId.parse(resource_id))
                    if replayed is None:
                        raise DomainError(
                            "INTERNAL_ERROR", "Stored idempotency resource is missing."
                        )
                    return replayed
            if await uow.users.get(user_id) is None:
                raise ResourceNotFoundError("user")
            if is_default:
                await uow.pools.clear_default(user_id, except_id=pool.id)
            await uow.pools.add(pool)
            if is_default:
                profile = await uow.profiles.get(user_id)
                if profile is None:
                    raise ResourceNotFoundError("profile")
                previous_version = profile.version
                profile.default_pool_id = pool.id
                profile.updated_at = datetime.now(UTC)
                profile.version += 1
                await uow.profiles.update(profile, expected_version=previous_version)
            await self._audit_only(
                uow,
                user_id,
                "athlete.pool_created",
                "Pool",
                pool.id,
                correlation_id,
                {"length_m": length_m, "is_default": is_default},
            )
            if idempotency_key is not None:
                await self._store_idempotency(
                    uow,
                    scope=f"{user_id}:pools:create",
                    key=idempotency_key,
                    request_hash=request_hash,
                    resource_id=pool.id,
                )
            await uow.commit()
        return pool

    async def update_pool(
        self,
        user_id: UserId,
        pool_id: EntityId,
        *,
        name: str,
        length_m: int,
        is_default: bool,
        active: bool,
        location_label: str | None,
        expected_version: int,
        correlation_id: CorrelationId,
    ) -> Pool:
        async with self._uow_factory() as uow:
            pool = await uow.pools.get(user_id, pool_id)
            if pool is None:
                raise ResourceNotFoundError("pool")
            if expected_version != pool.version:
                raise RevisionConflictError(pool.version)
            previous_version = pool.version
            pool.name = name
            pool.length = PoolLength(length_m)
            pool.is_default = is_default
            pool.active = active
            pool.location_label = location_label
            pool.updated_at = datetime.now(UTC)
            pool.version += 1
            pool.__post_init__()
            if is_default:
                await uow.pools.clear_default(user_id, except_id=pool.id)
            await uow.pools.update(pool, expected_version=previous_version)
            if is_default:
                profile = await uow.profiles.get(user_id)
                if profile is None:
                    raise ResourceNotFoundError("profile")
                previous_profile_version = profile.version
                profile.default_pool_id = pool.id
                profile.updated_at = datetime.now(UTC)
                profile.version += 1
                await uow.profiles.update(profile, expected_version=previous_profile_version)
            await self._audit_only(
                uow,
                user_id,
                "athlete.pool_updated",
                "Pool",
                pool.id,
                correlation_id,
                {"length_m": length_m, "is_default": is_default, "active": active},
            )
            await uow.commit()
            return pool

    async def list_availability(self, user_id: UserId) -> Sequence[AvailabilityRule]:
        async with self._uow_factory() as uow:
            return await uow.availability.list(user_id)

    async def replace_availability(
        self,
        user_id: UserId,
        inputs: Sequence[AvailabilityInput],
        *,
        correlation_id: CorrelationId,
    ) -> Sequence[AvailabilityRule]:
        rules = [
            AvailabilityRule(
                id=EntityId.new(),
                user_id=user_id,
                day_of_week=item.day_of_week,
                start_local_time=item.start_local_time,
                end_local_time=item.end_local_time,
                max_duration_minutes=item.max_duration_minutes,
                pool_id=item.pool_id,
                valid_from=item.valid_from,
                valid_until=item.valid_until,
                priority=item.priority,
            )
            for item in inputs
        ]
        async with self._uow_factory() as uow:
            if await uow.users.get(user_id) is None:
                raise ResourceNotFoundError("user")
            owned_pool_ids = {pool.id for pool in await uow.pools.list(user_id)}
            if any(
                rule.pool_id is not None and rule.pool_id not in owned_pool_ids for rule in rules
            ):
                raise ResourceNotFoundError("pool")
            await uow.availability.replace(user_id, rules)
            await self._audit_only(
                uow,
                user_id,
                "athlete.availability_replaced",
                "AvailabilityRule",
                None,
                correlation_id,
                {"rule_count": len(rules)},
            )
            await uow.commit()
        return rules

    async def list_goals(self, user_id: UserId) -> Sequence[TrainingGoal]:
        async with self._uow_factory() as uow:
            return await uow.goals.list(user_id)

    async def create_goal(
        self,
        user_id: UserId,
        *,
        title: str,
        target_distance_m: int,
        target_duration_seconds: Decimal,
        target_date: date | None,
        priority: int,
        correlation_id: CorrelationId,
        idempotency_key: IdempotencyKey | None = None,
        request_hash: str | None = None,
    ) -> TrainingGoal:
        goal = TrainingGoal(
            id=EntityId.new(),
            user_id=user_id,
            goal_type="distance_time",
            title=title,
            status=GoalStatus.ACTIVE,
            priority=priority,
            target_distance=Distance(target_distance_m),
            target_duration=Duration(target_duration_seconds),
            target_date=target_date,
        )
        async with self._uow_factory() as uow:
            if idempotency_key is not None:
                existing = await self._replay_idempotent(
                    uow,
                    scope=f"{user_id}:goals:create",
                    key=idempotency_key,
                    request_hash=request_hash,
                )
                if existing is not None:
                    resource_id = existing.response.get("resource_id")
                    if not isinstance(resource_id, str):
                        raise DomainError(
                            "INTERNAL_ERROR", "Stored idempotency response is invalid."
                        )
                    replayed = await uow.goals.get(user_id, EntityId.parse(resource_id))
                    if replayed is None:
                        raise DomainError(
                            "INTERNAL_ERROR", "Stored idempotency resource is missing."
                        )
                    return replayed
            if await uow.users.get(user_id) is None:
                raise ResourceNotFoundError("user")
            await uow.goals.add(goal)
            await self._record_change(
                uow,
                user_id=user_id,
                aggregate_type="TrainingGoal",
                aggregate_id=goal.id,
                event_type="swim_coach.goals.goal_activated.v1",
                action="goals.goal_created",
                payload={"goal_id": str(goal.id)},
                correlation_id=correlation_id,
            )
            if idempotency_key is not None:
                await self._store_idempotency(
                    uow,
                    scope=f"{user_id}:goals:create",
                    key=idempotency_key,
                    request_hash=request_hash,
                    resource_id=goal.id,
                )
            await uow.commit()
        return goal

    async def update_goal(
        self,
        user_id: UserId,
        goal_id: EntityId,
        *,
        title: str,
        target_distance_m: int,
        target_duration_seconds: Decimal,
        target_date: date | None,
        priority: int,
        status: GoalStatus,
        expected_version: int,
        correlation_id: CorrelationId,
    ) -> TrainingGoal:
        async with self._uow_factory() as uow:
            goal = await uow.goals.get(user_id, goal_id)
            if goal is None:
                raise ResourceNotFoundError("goal")
            if expected_version != goal.version:
                raise RevisionConflictError(goal.version)
            previous_version = goal.version
            goal.title = title
            goal.target_distance = Distance(target_distance_m)
            goal.target_duration = Duration(target_duration_seconds)
            goal.target_date = target_date
            goal.priority = priority
            goal.status = status
            goal.updated_at = datetime.now(UTC)
            goal.version += 1
            goal.__post_init__()
            await uow.goals.update(goal, expected_version=previous_version)
            await self._record_change(
                uow,
                user_id=user_id,
                aggregate_type="TrainingGoal",
                aggregate_id=goal.id,
                event_type="swim_coach.goals.goal_updated.v1",
                action="goals.goal_updated",
                payload={"goal_id": str(goal.id), "goal_version": goal.version},
                correlation_id=correlation_id,
            )
            await uow.commit()
            return goal

    @staticmethod
    async def _record_change(
        uow: UnitOfWork,
        *,
        user_id: UserId,
        aggregate_type: str,
        aggregate_id: EntityId,
        event_type: str,
        action: str,
        payload: dict[str, str | int | bool],
        correlation_id: CorrelationId,
    ) -> None:
        await uow.outbox.add(
            OutboxEvent(
                id=EntityId.new(),
                aggregate_type=aggregate_type,
                aggregate_id=aggregate_id,
                event_type=event_type,
                payload=dict(payload),
                user_id=user_id,
                correlation_id=correlation_id,
            )
        )
        await ContextService._audit_only(
            uow,
            user_id,
            action,
            aggregate_type,
            aggregate_id,
            correlation_id,
            dict(payload),
        )

    @staticmethod
    async def _audit_only(
        uow: UnitOfWork,
        user_id: UserId,
        action: str,
        entity_type: str,
        entity_id: EntityId | None,
        correlation_id: CorrelationId,
        after: dict[str, str | int | bool],
    ) -> None:
        await uow.audit.add(
            AuditEvent(
                id=EntityId.new(),
                user_id=user_id,
                actor_type="user",
                actor_id=str(user_id),
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                correlation_id=correlation_id,
                after=dict(after),
            )
        )

    @staticmethod
    async def _replay_idempotent(
        uow: UnitOfWork,
        *,
        scope: str,
        key: IdempotencyKey,
        request_hash: str | None,
    ) -> ApiIdempotencyRecord | None:
        if request_hash is None:
            raise DomainError("VALIDATION_FAILED", "A request hash is required for idempotency.")
        record = await uow.idempotency.get(scope, key.value, datetime.now(UTC))
        if record is not None and record.request_hash != request_hash:
            raise DomainError(
                "IDEMPOTENCY_CONFLICT",
                "This idempotency key was already used for a different request.",
            )
        return record

    @staticmethod
    async def _store_idempotency(
        uow: UnitOfWork,
        *,
        scope: str,
        key: IdempotencyKey,
        request_hash: str | None,
        resource_id: EntityId,
    ) -> None:
        if request_hash is None:
            raise DomainError("VALIDATION_FAILED", "A request hash is required for idempotency.")
        now = datetime.now(UTC)
        await uow.idempotency.add(
            ApiIdempotencyRecord(
                scope=scope,
                idempotency_key=key.value,
                request_hash=request_hash,
                response_status=201,
                response={"resource_id": str(resource_id)},
                created_at=now,
                expires_at=now + timedelta(hours=24),
            )
        )
