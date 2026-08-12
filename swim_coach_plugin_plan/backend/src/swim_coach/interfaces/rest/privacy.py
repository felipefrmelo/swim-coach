"""Authenticated data portability and deliberately staged account deletion."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Response, status
from pydantic import BaseModel, ConfigDict, Field

from swim_coach.domain.operations import DataExport, DeletionRequest
from swim_coach.domain.shared.value_objects import EntityId
from swim_coach.interfaces.rest.dependencies import (
    Authenticated,
    CsrfAuthenticated,
    RequestCorrelationId,
    Services,
)

router = APIRouter(prefix="/api/v1/privacy", tags=["privacy"])
IdempotencyHeader = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=200)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExportResponse(StrictModel):
    id: UUID
    status: str
    checksum: str | None
    size_bytes: int | None
    expires_at: datetime | None
    download_url: str | None

    @classmethod
    def from_domain(cls, item: DataExport) -> "ExportResponse":
        return cls(
            id=item.id.value,
            status=item.status.value,
            checksum=item.checksum,
            size_bytes=item.size_bytes,
            expires_at=item.expires_at,
            download_url=(
                f"/api/v1/privacy/exports/{item.id}/download" if item.storage_key else None
            ),
        )


class DeletionResponse(StrictModel):
    id: UUID
    status: str
    execute_after: datetime
    confirmation_phrase: str | None = None

    @classmethod
    def from_domain(
        cls, item: DeletionRequest, *, include_phrase: bool = False
    ) -> "DeletionResponse":
        return cls(
            id=item.id.value,
            status=item.status.value,
            execute_after=item.execute_after,
            confirmation_phrase=f"DELETE {item.id}" if include_phrase else None,
        )


class ConfirmDeletionRequest(StrictModel):
    confirmation: str = Field(min_length=40, max_length=50)


@router.post("/exports", response_model=ExportResponse, status_code=status.HTTP_201_CREATED)
async def create_export(
    idempotency_key: IdempotencyHeader,
    authenticated: CsrfAuthenticated,
    services: Services,
    correlation_id: RequestCorrelationId,
) -> ExportResponse:
    item = await services.privacy.create_export(
        authenticated.user.id,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )
    return ExportResponse.from_domain(item)


@router.get("/exports/{export_id}/download")
async def download_export(
    export_id: UUID,
    authenticated: Authenticated,
    services: Services,
) -> Response:
    payload, item = await services.privacy.export_payload(
        authenticated.user.id, EntityId(export_id)
    )
    return Response(
        content=payload,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="swim-coach-export-{item.id}.zip"',
            "Digest": f"sha-256={item.checksum}",
            "Cache-Control": "no-store",
        },
    )


@router.post(
    "/deletion-requests",
    response_model=DeletionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def request_deletion(
    idempotency_key: IdempotencyHeader,
    authenticated: CsrfAuthenticated,
    services: Services,
    correlation_id: RequestCorrelationId,
) -> DeletionResponse:
    item = await services.privacy.request_deletion(
        authenticated.user.id,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )
    return DeletionResponse.from_domain(item, include_phrase=True)


@router.post("/deletion-requests/{request_id}/confirm", response_model=DeletionResponse)
async def confirm_deletion(
    request_id: UUID,
    payload: ConfirmDeletionRequest,
    authenticated: CsrfAuthenticated,
    services: Services,
    correlation_id: RequestCorrelationId,
) -> DeletionResponse:
    item = await services.privacy.confirm_deletion(
        authenticated.user.id,
        EntityId(request_id),
        payload.confirmation,
        correlation_id=correlation_id,
    )
    return DeletionResponse.from_domain(item)
