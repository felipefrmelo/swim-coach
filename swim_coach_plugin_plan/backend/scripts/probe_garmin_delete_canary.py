"""Create, publish and delete one explicitly confirmed disposable Garmin workout."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date, timedelta

from swim_coach.bootstrap.container import AppServices, build_services
from swim_coach.domain.operations import JobStatus
from swim_coach.domain.shared.value_objects import CorrelationId, EntityId, UserId
from swim_coach.domain.workouts import CanonicalWorkout
from swim_coach.settings import get_settings

CONFIRMATION = "DELETE-CANARY"


def canary_definition() -> CanonicalWorkout:
    return CanonicalWorkout.model_validate(
        {
            "schema_version": "1.0",
            "title": "[P14 DELETE CANARY] 200 m",
            "sport": "POOL_SWIMMING",
            "pool_length_m": 20,
            "purpose": "TECHNIQUE",
            "tags": ["p14", "delete-canary", "disposable"],
            "nodes": [
                {
                    "type": "step",
                    "id": "canary",
                    "step_role": "WORK",
                    "end_condition": {"type": "distance", "meters": 200},
                    "intensity": "EASY",
                }
            ],
        }
    )


async def wait_for_job(services: AppServices, user_id: UserId, job_id: EntityId) -> JobStatus:
    for _ in range(90):
        async with services.uow_factory() as uow:
            job = await uow.jobs.get(user_id, job_id)
        if job is not None and job.status in {
            JobStatus.SUCCEEDED,
            JobStatus.FAILED_TERMINAL,
            JobStatus.NEEDS_RECONCILIATION,
        }:
            return job.status
        await asyncio.sleep(1)
    raise TimeoutError("canary job did not finish within 90 seconds")


async def run() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm-real-write", required=True)
    args = parser.parse_args()
    if args.confirm_real_write != CONFIRMATION:
        raise SystemExit(f"pass --confirm-real-write {CONFIRMATION}")

    services = build_services(get_settings())
    detail = None
    deletion_requested = False
    try:
        async with services.uow_factory() as uow:
            users = await uow.users.list_active()
        if len(users) != 1:
            raise RuntimeError("delete canary requires exactly one active user")
        user = users[0]
        pools = await services.context.list_pools(user.id)
        pool = next((item for item in pools if item.is_default), pools[0] if pools else None)
        if pool is None or pool.length.meters != 20:
            raise RuntimeError("delete canary requires the configured 20 m pool")

        detail = await services.coach_commands.save_workout(
            user.id,
            canary_definition(),
            workout_id=None,
            pool_id=pool.id,
            scheduled_date=date.today() + timedelta(days=14),
            scheduled_start_time=None,
            change_reason="P14 disposable deletion canary",
            correlation_id=CorrelationId.new(),
        )
        publish = await services.coach_commands.publish_workout(
            user.id,
            detail.workout.id,
            scheduled_date=None,
            scheduled_start_time=None,
            device_id=None,
            correlation_id=CorrelationId.new(),
        )
        if publish.job_id is None:
            raise RuntimeError("canary publication unexpectedly replayed")
        publish_status = await wait_for_job(services, user.id, publish.job_id)
        if publish_status is not JobStatus.SUCCEEDED:
            raise RuntimeError(f"canary publish finished as {publish_status.value}")

        deletion = await services.coach_commands.delete_workout(
            user.id,
            detail.workout.id,
            correlation_id=CorrelationId.new(),
        )
        deletion_requested = True
        delete_status = await wait_for_job(services, user.id, deletion.job_id)
        async with services.uow_factory() as uow:
            remaining = await uow.workouts.get(user.id, detail.workout.id)
        print(
            json.dumps(
                {
                    "canary": "p14_garmin_delete",
                    "publish_job": publish_status.value,
                    "delete_job": delete_status.value,
                    "local_workout_removed": remaining is None,
                    "recorded_activity_delete_attempted": False,
                },
                sort_keys=True,
            )
        )
        if delete_status is not JobStatus.SUCCEEDED or remaining is not None:
            raise RuntimeError("delete canary did not complete cleanly")
    finally:
        if detail is not None and not deletion_requested:
            try:
                deletion = await services.coach_commands.delete_workout(
                    detail.workout.user_id,
                    detail.workout.id,
                    correlation_id=CorrelationId.new(),
                )
                await wait_for_job(services, detail.workout.user_id, deletion.job_id)
            except Exception as error:
                print(
                    json.dumps(
                        {
                            "canary_cleanup": "failed",
                            "error_type": type(error).__name__,
                        },
                        sort_keys=True,
                    )
                )
        await services.database.dispose()


if __name__ == "__main__":
    asyncio.run(run())
