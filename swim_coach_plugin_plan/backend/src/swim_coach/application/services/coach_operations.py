"""Shared ChatGPT/PWA operational views and atomic calendar reconciliation."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import Any, cast
from zoneinfo import ZoneInfo

from swim_coach.application.ports.repositories import UnitOfWorkFactory
from swim_coach.application.services.garmin_upsert import GarminUpsertService
from swim_coach.application.services.garmin_workout_compiler import GarminWorkoutCompiler
from swim_coach.application.services.workouts import WorkoutService
from swim_coach.domain.goals import GoalStatus, TrainingGoal
from swim_coach.domain.operations import AuditEvent, Job, OutboxEvent
from swim_coach.domain.planning import PlanStatus, canonical_json_hash
from swim_coach.domain.shared.errors import (
    DomainError,
    ResourceNotFoundError,
    RevisionConflictError,
)
from swim_coach.domain.shared.types import JsonObject
from swim_coach.domain.shared.value_objects import (
    CorrelationId,
    Distance,
    Duration,
    EntityId,
    UserId,
)
from swim_coach.domain.workouts import PlannedWorkoutStatus, WorkoutSchedule, validate_workout
from swim_coach.domain.workouts.calendar import CalendarRequest, local_instant, resolve_calendar


def account_ref(user_id: UserId) -> str:
    return hashlib.sha256(f"swim-coach-account:{user_id}".encode()).hexdigest()[:24]


class CoachOperations:
    def __init__(self, uow_factory: UnitOfWorkFactory, *, garmin_write_enabled: bool) -> None:
        self._uow_factory = uow_factory
        self._garmin_write_enabled = garmin_write_enabled

    async def set_goal(
        self,
        user_id: UserId,
        *,
        title: str,
        distance_m: int,
        duration_seconds: int,
        expected_goal_version: int,
        correlation_id: CorrelationId,
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        async with self._uow_factory() as uow:
            await uow.idempotency.lock("coach-goal", str(user_id))
            goals = await uow.goals.list(user_id)
            current = next((g for g in goals if g.status is GoalStatus.ACTIVE), None)
            if (
                current
                and current.title == title
                and current.target_distance.meters == distance_m
                and current.target_duration.seconds == duration_seconds
            ):
                return {"goal_id": str(current.id), "replayed": True}
            if current is None or current.version != expected_goal_version:
                raise DomainError(
                    "REVISION_CONFLICT", "Reload the current goal before changing it."
                )
            goal = TrainingGoal(
                id=EntityId.new(),
                user_id=user_id,
                goal_type="distance_time",
                title=title,
                status=GoalStatus.ACTIVE,
                priority=0,
                target_distance=Distance(distance_m),
                target_duration=Duration(Decimal(duration_seconds)),
                metadata={"previous_goal_id": str(current.id)},
                created_at=now,
                updated_at=now,
            )
            for existing in goals:
                if existing.priority == 0:
                    previous = existing.version
                    existing.priority = 1
                    existing.version += 1
                    existing.updated_at = now
                    await uow.goals.update(existing, expected_version=previous)
            await uow.goals.add(goal)
            event: JsonObject = {
                "goal_id": str(goal.id),
                "previous_goal_id": str(current.id),
                "distance_m": distance_m,
                "duration_seconds": duration_seconds,
                "pace_seconds_per_100m": float(goal.target_pace.seconds_per_100m),
                "plan_changed": False,
            }
            await uow.audit.add(
                AuditEvent(
                    id=EntityId.new(),
                    user_id=user_id,
                    actor_type="user",
                    actor_id=str(user_id),
                    action="goal.current_changed",
                    entity_type="TrainingGoal",
                    entity_id=goal.id,
                    correlation_id=correlation_id,
                    after=event,
                )
            )
            await uow.outbox.add(
                OutboxEvent(
                    id=EntityId.new(),
                    user_id=user_id,
                    aggregate_type="TrainingGoal",
                    aggregate_id=goal.id,
                    event_type="swim_coach.goals.current_changed.v1",
                    payload=event,
                    correlation_id=correlation_id,
                )
            )
            await uow.commit()
        return {**event, "version": goal.version}

    async def associate(
        self,
        user_id: UserId,
        workout_id: EntityId,
        *,
        plan_id: EntityId,
        session_intent_id: EntityId,
        expected_revision: int,
        correlation_id: CorrelationId,
    ) -> dict[str, Any]:
        async with self._uow_factory() as uow:
            await uow.idempotency.lock("training-plan-live", str(user_id))
            await uow.idempotency.lock("coach-calendar", str(user_id))
            plan = await uow.training_plans.get_for_update(user_id, plan_id)
            if plan is None:
                raise ResourceNotFoundError("training_plan")
            if plan.current_revision != expected_revision or plan.status is not PlanStatus.ACTIVE:
                raise DomainError("PLAN_REVISION_CONFLICT", "Reload the active plan.")
            revision = await uow.training_plan_revisions.get(user_id, plan_id, expected_revision)
            intent = (
                next(
                    (
                        i
                        for w in revision.document.weeks
                        for i in w.sessions
                        if i.session_intent_id == str(session_intent_id)
                    ),
                    None,
                )
                if revision
                else None
            )
            detail = await WorkoutService._get_detail(uow, user_id, workout_id)
            if intent is None or intent.workout is None or detail.schedule is None:
                raise DomainError(
                    "PLAN_SESSION_LOCKED",
                    "Only an exact detailed intention can adopt a scheduled workout.",
                )
            from swim_coach.domain.workouts import canonical_content_hash

            if (
                canonical_content_hash(intent.workout) != detail.current_revision.content_hash
                or intent.pool_id != str(detail.workout.pool_id)
                or intent.scheduled_date != detail.schedule.scheduled_date
                or intent.scheduled_start_time != detail.schedule.scheduled_start_time
            ):
                raise DomainError(
                    "PLAN_SESSION_LOCKED",
                    "Workout content, pool and schedule must match the approved intent exactly.",
                )
            binding = await uow.plan_session_bindings.get_by_intent(
                user_id, plan_id, session_intent_id
            )
            existing = await uow.plan_session_bindings.get_by_workout(user_id, workout_id)
            if binding is None or binding.locked or (existing and existing.id != binding.id):
                raise DomainError(
                    "PLAN_SESSION_LOCKED",
                    "The session or workout already has a different association.",
                )
            if binding.workout_id is not None and binding.workout_id != workout_id:
                generated = await uow.workouts.get(user_id, binding.workout_id)
                remote = await uow.external_workout_bindings.get_by_workout(
                    user_id, "garmin", binding.workout_id
                )
                match = await uow.activity_data.get_match_by_workout(user_id, binding.workout_id)
                if (
                    generated is None
                    or remote is not None
                    or match is not None
                    or generated.status is PlannedWorkoutStatus.COMPLETED
                ):
                    raise DomainError(
                        "PLAN_SESSION_LOCKED",
                        "The materialized session has external state; resolve it before adoption.",
                    )
                version = generated.version
                generated.status = PlannedWorkoutStatus.ARCHIVED
                generated.version += 1
                generated.updated_at = datetime.now(UTC)
                await uow.workouts.update(generated, expected_version=version)
                await uow.workout_schedules.delete(user_id, generated.id)
            if binding.workout_id == workout_id:
                return {"workout_id": str(workout_id), "replayed": True, "garmin_changed": False}
            previous = binding.version
            binding.workout_id = workout_id
            binding.materialized_plan_revision = expected_revision
            binding.materialized_workout_hash = detail.current_revision.content_hash
            from swim_coach.domain.planning import PlanSessionState

            binding.state = PlanSessionState.MATERIALIZED
            binding.version += 1
            binding.updated_at = datetime.now(UTC)
            await uow.plan_session_bindings.update(binding, expected_version=previous)
            await uow.audit.add(
                AuditEvent(
                    id=EntityId.new(),
                    user_id=user_id,
                    actor_type="user",
                    actor_id=str(user_id),
                    action="workout.associated_to_plan",
                    entity_type="PlannedWorkout",
                    entity_id=workout_id,
                    correlation_id=correlation_id,
                    after={
                        "plan_id": str(plan_id),
                        "session_intent_id": str(session_intent_id),
                        "garmin_changed": False,
                    },
                )
            )
            await uow.commit()
        return {"workout_id": str(workout_id), "plan_id": str(plan_id), "garmin_changed": False}

    async def overview(self, user_id: UserId) -> dict[str, Any]:
        now = datetime.now(UTC)
        async with self._uow_factory() as uow:
            user = await uow.users.get(user_id)
            if user is None:
                raise ResourceNotFoundError("user")
            goals = sorted(await uow.goals.list(user_id), key=lambda g: (g.priority, str(g.id)))
            goal = next((g for g in goals if g.status is GoalStatus.ACTIVE), None)
            plans = await uow.training_plans.list(user_id)
            today = now.astimezone(ZoneInfo(user.timezone)).date()
            goal_data = (
                None
                if goal is None
                else {
                    "goal_id": str(goal.id),
                    "title": goal.title,
                    "distance_m": goal.target_distance.meters,
                    "duration_seconds": float(goal.target_duration.seconds),
                    "pace_seconds_per_100m": float(goal.target_pace.seconds_per_100m),
                    "distance_unit": "m",
                    "duration_unit": "s",
                    "version": goal.version,
                    "effective_at": goal.updated_at.isoformat(),
                }
            )
            cycles = [
                {
                    "plan_id": str(p.id),
                    "title": p.title,
                    "status": p.status.value,
                    "lifecycle_state": p.lifecycle_state(today),
                    "start_date": p.start_date.isoformat(),
                    "end_date": p.end_date.isoformat(),
                    "revision": p.current_revision,
                    "version": p.version,
                    "predecessor_plan_id": str(p.predecessor_plan_id)
                    if p.predecessor_plan_id
                    else None,
                    "goal_snapshot": p.goal_snapshot,
                    "goal_relationship": "CURRENT"
                    if goal
                    and p.goal_id == goal.id
                    and p.goal_snapshot.get("version") == goal.version
                    else "PREVIOUS_OR_UNVERIFIED",
                    "actions": ["PROPOSE_SUCCESSOR", "COMPLETE", "CANCEL"]
                    if p.status in {PlanStatus.ACTIVE, PlanStatus.PAUSED}
                    else [],
                }
                for p in plans
            ]
            workouts = await uow.workouts.list(user_id)
            schedules = {
                s.workout_id: s
                for s in await uow.workout_schedules.list(user_id, [w.id for w in workouts])
            }
            agenda: list[dict[str, Any]] = []
            for workout in workouts:
                schedule = schedules.get(workout.id)
                if workout.status in {
                    PlannedWorkoutStatus.ARCHIVED,
                    PlannedWorkoutStatus.CANCELLED,
                    PlannedWorkoutStatus.DELETING,
                }:
                    continue
                binding = await uow.plan_session_bindings.get_by_workout(user_id, workout.id)
                revision = (
                    await uow.workout_revisions.get(user_id, workout.current_revision_id)
                    if workout.current_revision_id
                    else None
                )
                match = await uow.activity_data.get_match_by_workout(user_id, workout.id)
                agenda.append(
                    {
                        "workout_id": str(workout.id),
                        "title": workout.title,
                        "version": workout.version,
                        "scheduled_date": schedule.scheduled_date.isoformat() if schedule else None,
                        "weekday": schedule.scheduled_date.strftime("%A").upper()
                        if schedule
                        else None,
                        "scheduled_start_time": schedule.scheduled_start_time.isoformat(
                            timespec="minutes"
                        )
                        if schedule and schedule.scheduled_start_time
                        else None,
                        "timezone": schedule.timezone if schedule else user.timezone,
                        "pool_length_m": revision.definition.pool_length_m if revision else None,
                        "distance_m": revision.totals.distance_m if revision else None,
                        "provenance": "PLAN_SESSION"
                        if binding
                        else "CONTINGENCY"
                        if workout.source == "contingency"
                        else "AD_HOC",
                        "plan_id": str(binding.plan_id) if binding else None,
                        "session_intent_id": str(binding.session_intent_id) if binding else None,
                        "activity_id": str(match.activity_id) if match else None,
                        "completed": match is not None
                        or workout.status is PlannedWorkoutStatus.COMPLETED,
                    }
                )
            agenda.sort(
                key=lambda w: (w["scheduled_date"] or "9999", w["scheduled_start_time"] or "")
            )
            jobs = await uow.jobs.list_recent(user_id, limit=100)
            timeline = [
                {
                    "type": "CYCLE",
                    "at": p.created_at.isoformat(),
                    "title": p.title,
                    "status": p.status.value,
                    "plan_id": str(p.id),
                }
                for p in plans
            ]
        return {
            "account": {"account_ref": account_ref(user_id), "display_name": user.display_name},
            "timezone": user.timezone,
            "as_of": now.isoformat(),
            "local_date": today.isoformat(),
            "current_goal": goal_data,
            "cycles": cycles,
            "agenda": agenda,
            "next_workout": next(
                (
                    w
                    for w in agenda
                    if w["scheduled_date"]
                    and w["scheduled_date"] >= today.isoformat()
                    and not w["completed"]
                ),
                None,
            ),
            "pending_jobs": [
                {
                    "job_id": str(j.id),
                    "state": j.status.value,
                    "type": j.job_type,
                    "updated_at": j.updated_at.isoformat(),
                    "error": j.last_error,
                }
                for j in jobs
                if j.status.value != "SUCCEEDED"
            ],
            "timeline": sorted(timeline, key=lambda e: e["at"]),
        }

    async def preview(
        self,
        user_id: UserId,
        *,
        requests: list[CalendarRequest],
        reference: datetime | None,
        timezone: str | None,
        start: time | None,
        workout_id: EntityId | None = None,
    ) -> dict[str, Any]:
        state = await self.overview(user_id)
        zone = timezone or state["timezone"]
        ref = reference or datetime.now(UTC)
        async with self._uow_factory() as uow:
            rules = await uow.availability.list(user_id)
            pools = await uow.pools.list(user_id)
        sessions: list[dict[str, Any]] = []
        for request in requests:
            day = resolve_calendar(request, reference=ref, timezone=zone)
            matches = [
                r
                for r in rules
                if r.day_of_week == day.weekday()
                and (r.valid_from is None or r.valid_from <= day)
                and (r.valid_until is None or r.valid_until >= day)
            ]
            if start is not None:
                matches = [r for r in matches if r.start_local_time <= start < r.end_local_time]
            rule = (
                sorted(matches, key=lambda r: (-r.priority, r.start_local_time))[0]
                if matches
                else None
            )
            local_start = start or (rule.start_local_time if rule else None)
            if local_start:
                local_instant(day, local_start, zone)
            max_minutes = None
            if rule and local_start:
                max_minutes = min(
                    rule.max_duration_minutes,
                    int(
                        (
                            datetime.combine(day, rule.end_local_time)
                            - datetime.combine(day, local_start)
                        ).total_seconds()
                        / 60
                    ),
                )
            pool = next(
                (p for p in pools if p.active and rule and p.id == rule.pool_id), None
            ) or next((p for p in pools if p.active and p.is_default), None)
            conflicts = [
                w["workout_id"]
                for w in state["agenda"]
                if w["workout_id"] != str(workout_id)
                and w["scheduled_date"] == day.isoformat()
                and not w["completed"]
            ]
            if any(s["scheduled_date"] == day.isoformat() for s in sessions):
                conflicts.append("DUPLICATE_REQUEST")
            sessions.append(
                {
                    "scheduled_date": day.isoformat(),
                    "weekday": day.strftime("%A").upper(),
                    "scheduled_start_time": local_start.isoformat(timespec="minutes")
                    if local_start
                    else None,
                    "timezone": zone,
                    "max_duration_minutes": max_minutes,
                    "pool_id": str(pool.id) if pool else None,
                    "pool_length_m": pool.length.meters if pool else None,
                    "conflicts": conflicts,
                    "available": rule is not None,
                }
            )
        result = {
            "reference": ref.isoformat(),
            "timezone": zone,
            "sessions": sessions,
            "session_count": len(sessions),
            "calendar_hash": canonical_json_hash({"agenda": cast(Any, state["agenda"])}),
            "account": state["account"],
        }
        return result

    async def publication_status(
        self, user_id: UserId, workout_ids: list[EntityId]
    ) -> dict[str, Any]:
        items = []
        async with self._uow_factory() as uow:
            jobs = await uow.jobs.list_recent(user_id, limit=100)
            for workout_id in workout_ids:
                workout = await uow.workouts.get(user_id, workout_id)
                if workout is None:
                    raise ResourceNotFoundError("workout")
                schedule = await uow.workout_schedules.get(user_id, workout_id)
                binding = await uow.external_workout_bindings.get_by_workout(
                    user_id, "garmin", workout_id
                )
                job = next(
                    (j for j in jobs if j.payload.get("workout_id") == str(workout_id)), None
                )
                confirmed = bool(
                    binding
                    and binding.status.value == "SCHEDULED"
                    and schedule
                    and binding.scheduled_date == schedule.scheduled_date
                    and binding.revision_id == workout.current_revision_id
                )
                state = (
                    "PUBLISHED"
                    if confirmed
                    else "OUT_OF_SYNC"
                    if binding and binding.external_workout_id
                    else "NOT_PUBLISHED"
                )
                if job and job.status.value != "SUCCEEDED":
                    state = {
                        "QUEUED": "QUEUED",
                        "LEASED": "PROCESSING",
                        "RUNNING": "PROCESSING",
                        "RETRY_SCHEDULED": "RETRYING",
                        "FAILED_TERMINAL": "FAILED",
                        "NEEDS_RECONCILIATION": "OUT_OF_SYNC",
                    }[job.status.value]
                    confirmed = False
                revision = (
                    await uow.workout_revisions.get(user_id, workout.current_revision_id)
                    if workout.current_revision_id
                    else None
                )
                warnings = (
                    list(GarminWorkoutCompiler().compile(revision).warnings) if revision else []
                )
                items.append(
                    {
                        "workout_id": str(workout_id),
                        "warnings": warnings,
                        "state": state,
                        "remote_confirmed": confirmed,
                        "local_date": schedule.scheduled_date.isoformat() if schedule else None,
                        "remote_date": binding.scheduled_date.isoformat()
                        if binding and binding.scheduled_date
                        else None,
                        "last_verified_at": binding.updated_at.isoformat()
                        if binding and binding.external_workout_id
                        else None,
                        "job_id": str(job.id) if job else None,
                        "job_state": job.status.value if job else None,
                        "error": job.last_error if job else None,
                    }
                )
        return {
            "items": items,
            "all_published": bool(items) and all(i["remote_confirmed"] for i in items),
        }

    async def reschedule(
        self,
        user_id: UserId,
        workout_id: EntityId,
        *,
        request: CalendarRequest,
        start: time | None,
        expected_version: int,
        expected_calendar_hash: str,
        correlation_id: CorrelationId,
    ) -> dict[str, Any]:
        preview = await self.preview(
            user_id,
            requests=[request],
            reference=None,
            timezone=None,
            start=start,
            workout_id=workout_id,
        )
        slot = preview["sessions"][0]
        if preview["calendar_hash"] != expected_calendar_hash:
            async with self._uow_factory() as uow:
                current = await WorkoutService._get_detail(uow, user_id, workout_id)
                if (
                    current.workout.version == expected_version + 1
                    and current.schedule
                    and current.schedule.scheduled_date.isoformat() == slot["scheduled_date"]
                    and current.schedule.scheduled_start_time
                    and current.schedule.scheduled_start_time.isoformat(timespec="minutes")
                    == slot["scheduled_start_time"]
                    and current.current_revision.change_reason == "Calendar reschedule"
                ):
                    return {
                        "workout_id": str(workout_id),
                        "replayed": True,
                        "local_state": "SCHEDULED",
                        "remote_confirmed": False,
                        "next_tool": "get_publication_status",
                    }
            raise DomainError("REVISION_CONFLICT", "The calendar changed. Preview again.")
        if not slot["available"] or slot["conflicts"]:
            raise DomainError(
                "CALENDAR_CONFLICT", "Choose an available slot without another workout."
            )

        day = date.fromisoformat(slot["scheduled_date"])
        local_start = time.fromisoformat(slot["scheduled_start_time"])
        now = datetime.now(UTC)
        async with self._uow_factory() as uow:
            await uow.idempotency.lock("coach-calendar", str(user_id))
            current_workouts = await uow.workouts.list(user_id)
            for other in current_workouts:
                if other.id == workout_id or other.status in {
                    PlannedWorkoutStatus.CANCELLED,
                    PlannedWorkoutStatus.ARCHIVED,
                    PlannedWorkoutStatus.DELETING,
                }:
                    continue
                other_schedule = await uow.workout_schedules.get(user_id, other.id)
                if other_schedule and other_schedule.scheduled_date == day:
                    raise DomainError("CALENDAR_CONFLICT", "The calendar changed; preview again.")
            detail = await WorkoutService._get_detail(uow, user_id, workout_id)
            workout = detail.workout
            if workout.version != expected_version:
                # Retry of the exact same operation is safe after the version increment.
                if not (
                    detail.schedule
                    and detail.schedule.scheduled_date == day
                    and detail.schedule.scheduled_start_time == local_start
                ):
                    raise RevisionConflictError(workout.version)
                return {
                    "workout_id": str(workout_id),
                    "local_state": "SCHEDULED",
                    "remote_confirmed": False,
                    "replayed": True,
                }
            if workout.status in {
                PlannedWorkoutStatus.COMPLETED,
                PlannedWorkoutStatus.CANCELLED,
                PlannedWorkoutStatus.ARCHIVED,
                PlannedWorkoutStatus.DELETING,
            } or await uow.activity_data.get_match_by_workout(user_id, workout_id):
                raise DomainError("PLAN_SESSION_LOCKED", "A resolved workout cannot be moved.")
            binding = await uow.plan_session_bindings.get_by_workout(user_id, workout_id)
            if binding:
                raise DomainError(
                    "PLAN_SESSION_LOCKED",
                    "Propose a RESCHEDULE plan revision for a prescribed session.",
                    details={
                        "recovery": {"next_tool": "get_training_plan", "max_automatic_retries": 1}
                    },
                )
            totals = validate_workout(detail.current_revision.definition).totals
            if (totals.duration_max_seconds or totals.duration_min_seconds) > slot[
                "max_duration_minutes"
            ] * 60:
                raise DomainError(
                    "VALIDATION_FAILED", "Workout time exceeds this availability window."
                )
            external = await uow.external_workout_bindings.get_by_workout(
                user_id, "garmin", workout_id
            )
            if external and not self._garmin_write_enabled:
                raise DomainError(
                    "GARMIN_WRITE_DISABLED", "Reconciliation is disabled; calendar was not changed."
                )
            revision = replace(
                detail.current_revision,
                id=EntityId.new(),
                revision_number=max(r.revision_number for r in detail.revisions) + 1,
                change_reason="Calendar reschedule",
                created_at=now,
                totals=totals,
            )
            await uow.workout_revisions.add(revision)
            await uow.flush()
            schedule = WorkoutSchedule(
                id=detail.schedule.id if detail.schedule else EntityId.new(),
                workout_id=workout_id,
                scheduled_date=day,
                scheduled_start_time=local_start,
                timezone=preview["timezone"],
                pool_id=workout.pool_id,
            )
            await uow.workout_schedules.upsert(schedule)
            previous = workout.version
            workout.current_revision_id = workout.approved_revision_id = revision.id
            workout.status = PlannedWorkoutStatus.SCHEDULED
            workout.version += 1
            workout.updated_at = now
            await uow.workouts.update(workout, expected_version=previous)
            job = None
            if external:
                compiled = GarminWorkoutCompiler().compile(revision)
                job = await uow.jobs.add_idempotent(
                    Job(
                        id=EntityId.new(),
                        user_id=user_id,
                        job_type=GarminUpsertService.JOB_TYPE,
                        idempotency_key=f"garmin:move:{workout_id}:{revision.id}",
                        payload={
                            "workout_id": str(workout_id),
                            "revision_id": str(revision.id),
                            "binding_id": str(external.id),
                            "compiled_hash": compiled.compiled_hash,
                            "source_revision_hash": compiled.source_revision_hash,
                            "compiled_payload": compiled.payload,
                            "scheduled_date": day.isoformat(),
                            "warnings": list(compiled.warnings),
                        },
                        max_attempts=3,
                    )
                )
            event: JsonObject = {
                "workout_id": str(workout_id),
                "previous_date": detail.schedule.scheduled_date.isoformat()
                if detail.schedule
                else None,
                "scheduled_date": day.isoformat(),
                "job_id": str(job.id) if job else None,
                "remote_confirmed": False,
            }
            await uow.audit.add(
                AuditEvent(
                    id=EntityId.new(),
                    user_id=user_id,
                    actor_type="user",
                    actor_id=str(user_id),
                    action="workout.rescheduled",
                    entity_type="PlannedWorkout",
                    entity_id=workout_id,
                    correlation_id=correlation_id,
                    after=event,
                )
            )
            await uow.outbox.add(
                OutboxEvent(
                    id=EntityId.new(),
                    user_id=user_id,
                    aggregate_type="PlannedWorkout",
                    aggregate_id=workout_id,
                    event_type="swim_coach.workouts.rescheduled.v1",
                    payload=event,
                    correlation_id=correlation_id,
                )
            )
            await uow.commit()
        return {
            **event,
            "version": workout.version,
            "local_state": "SCHEDULED",
            "state": "QUEUED" if job else "NOT_PUBLISHED",
            "duration_complete": totals.duration_complete,
        }
