"""Timezone-aware, replay-safe automation that only creates internal work."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from swim_coach.application.ports.repositories import UnitOfWorkFactory
from swim_coach.domain.garmin import GarminConnectionStatus
from swim_coach.domain.operations import Job, Notification
from swim_coach.domain.shared.value_objects import EntityId


class AutomationService:
    """Materialize periodic jobs with stable keys for direct personal workflows."""

    SYNC_JOB_TYPE = "garmin.sync_activities"

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        *,
        sync_hour: int = 6,
        retention_days: int = 30,
        sync_enabled: bool = True,
    ) -> None:
        self._uow_factory = uow_factory
        self._sync_hour = sync_hour
        self._retention_days = retention_days
        self._sync_enabled = sync_enabled
        self._last_tick: datetime | None = None

    async def tick(self, now: datetime | None = None) -> int:
        now = (now or datetime.now(UTC)).astimezone(UTC)
        if self._last_tick is not None and now - self._last_tick < timedelta(minutes=1):
            return 0
        self._last_tick = now
        created = 0
        async with self._uow_factory() as uow:
            users = await uow.users.list_active()
            for user in users:
                try:
                    zone = ZoneInfo(user.timezone)
                    local_now = now.astimezone(zone)
                except ZoneInfoNotFoundError:
                    continue
                connection = await uow.garmin_connections.get(user.id)
                if (
                    local_now.hour >= self._sync_hour
                    and self._sync_enabled
                    and connection is not None
                    and connection.status
                    in {GarminConnectionStatus.ACTIVE, GarminConnectionStatus.DEGRADED}
                ):
                    key = f"automation:sync:{user.id}:{local_now.date().isoformat()}"
                    job = Job(
                        id=EntityId.new(),
                        user_id=user.id,
                        job_type=self.SYNC_JOB_TYPE,
                        payload={"trigger": "schedule", "force": False},
                        idempotency_key=key,
                        max_attempts=5,
                    )
                    persisted = await uow.jobs.add_idempotent(job)
                    created += int(persisted.id == job.id)
                activities = await uow.activities.list_recent(user.id, limit=10)
                recent = [
                    item
                    for item in activities
                    if 0
                    <= (local_now.date() - item.start_time_utc.astimezone(zone).date()).days
                    <= 7
                ]
                feedbacks = await uow.activity_data.list_feedbacks(
                    user.id, [item.id for item in recent]
                )
                feedback_activity_ids = {item.activity_id for item in feedbacks}
                for activity in recent:
                    if activity.id in feedback_activity_ids:
                        continue
                    notification = Notification(
                        id=EntityId.new(),
                        user_id=user.id,
                        notification_type="FEEDBACK_PENDING",
                        dedupe_key=f"feedback-pending:{activity.id}",
                        title="Como foi sua última natação?",
                        body="Um check-in curto ajuda a ajustar a próxima semana.",
                        link=f"/activities/{activity.id}",
                    )
                    persisted_notification = await uow.notifications.add_idempotent(notification)
                    created += int(persisted_notification.id == notification.id)
                workouts = await uow.workouts.list(user.id)
                schedules = await uow.workout_schedules.list(
                    user.id, [item.id for item in workouts]
                )
                for schedule in schedules:
                    if schedule.scheduled_date not in {
                        local_now.date(),
                        local_now.date() + timedelta(days=1),
                    }:
                        continue
                    notification = Notification(
                        id=EntityId.new(),
                        user_id=user.id,
                        notification_type="WORKOUT_REMINDER",
                        dedupe_key=(
                            f"workout-reminder:{schedule.workout_id}:"
                            f"{schedule.scheduled_date.isoformat()}"
                        ),
                        title="Treino próximo",
                        body="Abra o treino salvo para revisar os detalhes antes de nadar.",
                        link=f"/workouts/{schedule.workout_id}",
                    )
                    persisted_notification = await uow.notifications.add_idempotent(notification)
                    created += int(persisted_notification.id == notification.id)
            await uow.jobs.purge_finished(now - timedelta(days=self._retention_days))
            await uow.commit()
        return created
