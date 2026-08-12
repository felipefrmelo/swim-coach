from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from swim_coach.application.services.automation import AutomationService
from swim_coach.domain.garmin import GarminConnectionStatus
from swim_coach.domain.identity import AppUser
from swim_coach.domain.operations import Job
from swim_coach.domain.shared.value_objects import UserId


class FakeJobs:
    def __init__(self) -> None:
        self.items: dict[str, Job] = {}
        self.purge_before: datetime | None = None

    async def add_idempotent(self, job: Job) -> Job:
        assert job.idempotency_key is not None
        return self.items.setdefault(job.idempotency_key, job)

    async def purge_finished(self, before: datetime) -> int:
        self.purge_before = before
        return 0


class FakeUow:
    def __init__(self, user: AppUser, jobs: FakeJobs) -> None:
        self.users = SimpleNamespace(list_active=self._list_users)
        self.garmin_connections = SimpleNamespace(get=self._connection)
        self.activities = SimpleNamespace(list_recent=self._empty_recent)
        self.activity_data = SimpleNamespace(list_feedbacks=self._empty_feedbacks)
        self.workouts = SimpleNamespace(list=self._empty_workouts)
        self.workout_schedules = SimpleNamespace(list=self._empty_schedules)
        self.notifications = SimpleNamespace(add_idempotent=self._notification)
        self.jobs = jobs
        self.user = user
        self.commits = 0

    async def _list_users(self) -> list[AppUser]:
        return [self.user]

    async def _connection(self, _user_id: UserId) -> SimpleNamespace:
        return SimpleNamespace(status=GarminConnectionStatus.ACTIVE)

    async def _empty_recent(self, _user_id: UserId, *, limit: int) -> list[object]:
        assert limit == 10
        return []

    async def _empty_feedbacks(self, _user_id: UserId, _ids: list[object]) -> list[object]:
        return []

    async def _empty_workouts(self, _user_id: UserId) -> list[object]:
        return []

    async def _empty_schedules(self, _user_id: UserId, _ids: list[object]) -> list[object]:
        return []

    async def _notification(self, item: object) -> object:
        return item

    async def __aenter__(self) -> "FakeUow":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1


@pytest.mark.asyncio
async def test_scheduler_is_timezone_aware_and_replay_safe() -> None:
    user = AppUser(UserId.new(), "swimmer@example.test", "Swimmer")
    jobs = FakeJobs()
    uow = FakeUow(user, jobs)
    # Sunday 18:00 in America/Sao_Paulo.
    now = datetime(2026, 8, 16, 21, tzinfo=UTC)

    first = AutomationService(lambda: uow)
    replay = AutomationService(lambda: uow)

    assert await first.tick(now) == 2
    assert await replay.tick(now) == 0
    assert {job.job_type for job in jobs.items.values()} == {
        "garmin.sync_activities",
        "planning.generate_week",
    }
    planning = next(job for job in jobs.items.values() if job.job_type == "planning.generate_week")
    assert planning.payload == {"week_start": "2026-08-17"}
    assert jobs.purge_before == datetime(2026, 7, 17, 21, tzinfo=UTC)
