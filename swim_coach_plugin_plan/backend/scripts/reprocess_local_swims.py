"""Reprocess immutable local FIT artifacts without calling Garmin.

This is deliberately an operator command rather than an MCP/REST endpoint.  It
requires an explicit user UUID so one tenant can never be selected implicitly.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from typing import Protocol

from swim_coach.application.ports.garmin import GarminProviderError
from swim_coach.application.services.activity_data import ActivityDetail
from swim_coach.bootstrap.container import build_services
from swim_coach.domain.garmin import Activity
from swim_coach.domain.shared.errors import DomainError, ResourceNotFoundError
from swim_coach.domain.shared.value_objects import (
    Distance,
    Duration,
    EntityId,
    PoolLength,
    UserId,
)
from swim_coach.infrastructure.garmin.provider import map_activity
from swim_coach.settings import get_settings


class _LocalActivityProcessor(Protocol):
    async def process_local(self, user_id: UserId, activity_id: EntityId) -> ActivityDetail: ...


def _remap_activity_summary(
    activity: Activity, payload: dict[str, object], timezone: str
) -> Activity:
    """Reapply the current source adapter to one immutable persisted summary."""

    mapped = map_activity(payload)
    if mapped.external_id != activity.external_activity_id:
        raise ValueError("raw summary external id does not match the owned activity")
    legacy_moving = (
        mapped.moving_seconds if mapped.moving_seconds is not None else mapped.timer_seconds
    )

    return replace(
        activity,
        name=mapped.name,
        sport=mapped.sport,
        subtype=mapped.subtype,
        start_time_utc=mapped.start_time_utc,
        timezone=timezone,
        distance=Distance(mapped.distance_m),
        elapsed=Duration(mapped.elapsed_seconds),
        timer=Duration(mapped.timer_seconds),
        # Activity remains the frozen v1-compatible summary row. Canonical v2
        # readers expose moving only after FIT normalization.
        moving=Duration(legacy_moving),
        source_updated_at=mapped.provider_updated_at,
        pool_length=(
            PoolLength(mapped.pool_length_m)
            if mapped.pool_length_m is not None and mapped.pool_length_m > 0
            else None
        ),
        length_count=mapped.length_count,
        calories=mapped.calories,
        avg_hr=mapped.avg_hr,
        max_hr=mapped.max_hr,
        avg_pace_seconds_per_100m=mapped.avg_pace_seconds_per_100m,
        avg_stroke_rate=mapped.avg_stroke_rate,
        avg_strokes_per_length=mapped.avg_strokes_per_length,
        avg_swolf=mapped.avg_swolf,
        normalization_version="garmin-summary-v2",
        updated_at=datetime.now(UTC),
    )


async def _reprocess_fit(
    processor: _LocalActivityProcessor,
    user_id: UserId,
    activity_id: EntityId,
) -> str | None:
    """Reprocess one FIT while keeping a batch failure scoped to that activity."""

    try:
        detail = await processor.process_local(user_id, activity_id)
    except DomainError as error:
        print(f"{activity_id} skipped={error.code}")
        return None
    parser_version = (
        detail.normalized.normalization.parser_version if detail.normalized else "missing"
    )
    print(f"{activity_id} reprocessed parser={parser_version}")
    return parser_version


async def _run(user_id: UserId, activity_id: EntityId | None) -> int:
    services = build_services(get_settings())
    try:
        async with services.uow_factory() as uow:
            artifacts = await uow.activity_data.list_artifacts(user_id)
            activities = await uow.activities.list_all(user_id)
        fit_activity_ids = {item.activity_id for item in artifacts if item.artifact_type == "fit"}
        owned_activity_ids = {item.id for item in activities}
        if activity_id is not None and activity_id not in owned_activity_ids:
            raise ResourceNotFoundError("activity")
        activity_ids = (
            [activity_id]
            if activity_id is not None
            else sorted((item.id for item in activities), key=str)
        )
        reprocessed = 0
        for selected_id in activity_ids:
            async with services.uow_factory() as uow:
                activity = await uow.activities.get(user_id, selected_id)
                user = await uow.users.get(user_id)
                raw_summary = (
                    await uow.raw_provider_payloads.get(user_id, activity.raw_summary_id)
                    if activity is not None
                    else None
                )
                if activity is None or user is None:
                    raise ResourceNotFoundError("activity_or_user")
                if raw_summary is None:
                    print(f"{selected_id} summary=RAW_SUMMARY_UNAVAILABLE")
                else:
                    try:
                        remapped = _remap_activity_summary(
                            activity,
                            dict(raw_summary.payload),
                            user.timezone,
                        )
                    except (GarminProviderError, ValueError, TypeError) as error:
                        print(f"{selected_id} summary=REMAP_FAILED reason={type(error).__name__}")
                    else:
                        status, _ = await uow.activities.upsert(remapped)
                        await uow.commit()
                        print(f"{selected_id} summary={status.value}")
            if selected_id not in fit_activity_ids:
                print(f"{selected_id} skipped=FIT_FILE_UNAVAILABLE")
                continue
            parser = await _reprocess_fit(services.activity_data, user_id, selected_id)
            if parser is None:
                continue
            reprocessed += 1
        return reprocessed
    finally:
        await services.database.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--activity-id")
    args = parser.parse_args()
    count = asyncio.run(
        _run(
            UserId.parse(args.user_id),
            EntityId.parse(args.activity_id) if args.activity_id else None,
        )
    )
    print(f"reprocessed={count}")


if __name__ == "__main__":
    main()
