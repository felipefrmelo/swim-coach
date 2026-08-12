"""Authenticated Garmin status, device, sync and activity endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, Query, status

from swim_coach.domain.shared.errors import DomainError
from swim_coach.interfaces.rest.dependencies import Authenticated, CsrfAuthenticated, Services
from swim_coach.interfaces.rest.schemas import (
    ActivityResponse,
    GarminConnectionResponse,
    GarminDeviceResponse,
    SyncJobResponse,
    SyncRunResponse,
)

router = APIRouter(prefix="/api/v1/integrations/garmin", tags=["garmin"])
IdempotencyHeader = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=200)]


@router.get("", response_model=GarminConnectionResponse)
async def get_connection(
    authenticated: Authenticated,
    services: Services,
) -> GarminConnectionResponse:
    connection = (
        await services.garmin_connection.status(authenticated.user.id)
        if services.garmin_connection is not None
        else None
    )
    return GarminConnectionResponse.from_domain(
        connection,
        configured=services.garmin_connection is not None,
    )


@router.delete("", response_model=GarminConnectionResponse)
async def disconnect(
    authenticated: CsrfAuthenticated,
    services: Services,
) -> GarminConnectionResponse:
    if services.garmin_connection is None:
        raise DomainError("GARMIN_NOT_CONFIGURED", "Garmin is not configured on this server.")
    connection = await services.garmin_connection.disconnect(authenticated.user.id)
    return GarminConnectionResponse.from_domain(connection, configured=True)


@router.get("/devices", response_model=list[GarminDeviceResponse])
async def list_devices(
    authenticated: Authenticated,
    services: Services,
) -> list[GarminDeviceResponse]:
    async with services.uow_factory() as uow:
        devices = await uow.devices.list(authenticated.user.id)
    return [
        GarminDeviceResponse(
            id=device.id.value,
            model=device.model,
            name=device.name,
            is_primary=device.is_primary,
            last_seen_at=device.last_seen_at,
        )
        for device in devices
        if device.provider == "garmin"
    ]


@router.post("/sync", response_model=SyncJobResponse, status_code=status.HTTP_202_ACCEPTED)
async def request_sync(
    idempotency_key: IdempotencyHeader,
    authenticated: CsrfAuthenticated,
    services: Services,
) -> SyncJobResponse:
    if services.garmin_sync is None:
        raise DomainError("GARMIN_NOT_CONFIGURED", "Garmin is not configured on this server.")
    job = await services.garmin_sync.request_sync(authenticated.user.id, idempotency_key)
    return SyncJobResponse(id=job.id.value, status=job.status)


@router.get("/sync-runs", response_model=list[SyncRunResponse])
async def list_sync_runs(
    authenticated: Authenticated,
    services: Services,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[SyncRunResponse]:
    async with services.uow_factory() as uow:
        runs = await uow.sync_runs.list_recent(authenticated.user.id, limit=limit)
    return [SyncRunResponse.from_domain(run) for run in runs]


@router.get("/activities", response_model=list[ActivityResponse])
async def list_activities(
    authenticated: Authenticated,
    services: Services,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[ActivityResponse]:
    async with services.uow_factory() as uow:
        activities = await uow.activities.list_recent(authenticated.user.id, limit=limit)
    return [ActivityResponse.from_domain(activity) for activity in activities]
