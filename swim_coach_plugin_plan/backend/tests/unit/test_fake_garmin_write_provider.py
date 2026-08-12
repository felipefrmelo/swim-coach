"""Write provider contract and ambiguous-result reconciliation."""

from datetime import date

import pytest

from swim_coach.application.ports.garmin import GarminProviderError, GarminWorkoutDTO
from swim_coach.domain.shared.value_objects import UserId
from swim_coach.infrastructure.garmin import FakeGarminWorkoutProvider


def dto() -> GarminWorkoutDTO:
    return GarminWorkoutDTO(
        payload={"workoutName": "Canário descartável"},
        compiled_hash="a" * 64,
        source_revision_hash="b" * 64,
    )


@pytest.mark.asyncio
async def test_create_and_schedule_are_idempotent() -> None:
    provider = FakeGarminWorkoutProvider()
    user_id = UserId.new()
    first = await provider.create_workout(user_id, dto())
    replay = await provider.create_workout(user_id, dto())
    assert replay.external_workout_id == first.external_workout_id
    scheduled = await provider.schedule_workout(
        user_id, first.external_workout_id, date(2026, 8, 12)
    )
    schedule_replay = await provider.schedule_workout(
        user_id, first.external_workout_id, date(2026, 8, 12)
    )
    assert schedule_replay.external_schedule_id == scheduled.external_schedule_id
    restarted = FakeGarminWorkoutProvider()
    after_restart = await restarted.create_workout(user_id, dto())
    assert after_restart.external_workout_id == first.external_workout_id


@pytest.mark.asyncio
async def test_ambiguous_create_is_found_before_retry() -> None:
    provider = FakeGarminWorkoutProvider(ambiguous_create_once=True)
    user_id = UserId.new()
    with pytest.raises(GarminProviderError) as error:
        await provider.create_workout(user_id, dto())
    assert error.value.outcome_ambiguous
    reconciled = await provider.find_workout_by_source_hash(user_id, dto().source_revision_hash)
    assert reconciled is not None
    assert provider.create_calls == 1


@pytest.mark.asyncio
async def test_ambiguous_schedule_is_found_before_retry() -> None:
    provider = FakeGarminWorkoutProvider(ambiguous_schedule_once=True)
    user_id = UserId.new()
    workout = await provider.create_workout(user_id, dto())
    scheduled_date = date(2026, 8, 12)
    with pytest.raises(GarminProviderError) as error:
        await provider.schedule_workout(user_id, workout.external_workout_id, scheduled_date)
    assert error.value.outcome_ambiguous
    reconciled = await provider.find_schedule(user_id, workout.external_workout_id, scheduled_date)
    assert reconciled is not None
    assert provider.schedule_calls == 1
