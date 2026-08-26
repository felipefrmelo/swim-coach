"""Deterministic development adapter for P07 write-path tests."""

from __future__ import annotations

import hashlib
from datetime import date

from swim_coach.application.ports.garmin import (
    ExternalScheduleResult,
    ExternalWorkoutResult,
    GarminErrorCategory,
    GarminProviderError,
    GarminWorkoutDTO,
)
from swim_coach.domain.shared.value_objects import UserId


class FakeGarminWorkoutProvider:
    def __init__(
        self,
        *,
        ambiguous_create_once: bool = False,
        ambiguous_schedule_once: bool = False,
    ) -> None:
        self._workouts: dict[tuple[str, str], ExternalWorkoutResult] = {}
        self._schedules: dict[tuple[str, str, date], ExternalScheduleResult] = {}
        self._ambiguous_create_once = ambiguous_create_once
        self._ambiguous_schedule_once = ambiguous_schedule_once
        self.create_calls = 0
        self.schedule_calls = 0
        self.update_calls = 0
        self.unschedule_calls = 0

    async def create_workout(
        self, user_id: UserId, payload: GarminWorkoutDTO
    ) -> ExternalWorkoutResult:
        self.create_calls += 1
        key = (str(user_id), payload.source_revision_hash)
        result = self._workouts.get(key)
        if result is None:
            result = ExternalWorkoutResult(
                external_workout_id=f"fake-workout-{payload.source_revision_hash[:16]}",
                provider_payload={"compiled_hash": payload.compiled_hash},
            )
            self._workouts[key] = result
        if self._ambiguous_create_once:
            self._ambiguous_create_once = False
            raise GarminProviderError(
                GarminErrorCategory.NETWORK,
                retryable=True,
                outcome_ambiguous=True,
            )
        return result

    async def schedule_workout(
        self, user_id: UserId, external_workout_id: str, scheduled_date: date
    ) -> ExternalScheduleResult:
        self.schedule_calls += 1
        key = (str(user_id), external_workout_id, scheduled_date)
        result = self._schedules.get(key)
        if result is None:
            result = ExternalScheduleResult(
                external_schedule_id=(
                    "fake-schedule-"
                    + hashlib.sha256(
                        f"{external_workout_id}:{scheduled_date.isoformat()}".encode()
                    ).hexdigest()[:16]
                ),
                scheduled_date=scheduled_date,
            )
            self._schedules[key] = result
        if self._ambiguous_schedule_once:
            self._ambiguous_schedule_once = False
            raise GarminProviderError(
                GarminErrorCategory.NETWORK,
                retryable=True,
                outcome_ambiguous=True,
            )
        return result

    async def update_workout(
        self, user_id: UserId, external_workout_id: str, payload: GarminWorkoutDTO
    ) -> ExternalWorkoutResult:
        self.update_calls += 1
        previous_key = next(
            (
                key
                for key, value in self._workouts.items()
                if key[0] == str(user_id) and value.external_workout_id == external_workout_id
            ),
            None,
        )
        if previous_key is not None:
            self._workouts.pop(previous_key)
        result = ExternalWorkoutResult(
            external_workout_id=external_workout_id,
            provider_payload={"compiled_hash": payload.compiled_hash},
        )
        self._workouts[(str(user_id), payload.source_revision_hash)] = result
        return result

    async def unschedule_workout(self, user_id: UserId, external_schedule_id: str) -> None:
        self.unschedule_calls += 1
        for key, value in list(self._schedules.items()):
            if key[0] == str(user_id) and value.external_schedule_id == external_schedule_id:
                self._schedules.pop(key)

    async def find_workout_by_source_hash(
        self, user_id: UserId, source_revision_hash: str
    ) -> ExternalWorkoutResult | None:
        return self._workouts.get((str(user_id), source_revision_hash))

    async def find_schedule(
        self, user_id: UserId, external_workout_id: str, scheduled_date: date
    ) -> ExternalScheduleResult | None:
        return self._schedules.get((str(user_id), external_workout_id, scheduled_date))
