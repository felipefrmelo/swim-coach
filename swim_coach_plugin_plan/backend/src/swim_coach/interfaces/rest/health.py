"""Process health endpoints with no private data."""

from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict

from swim_coach.domain.shared.errors import DomainError

router = APIRouter(prefix="/health", tags=["operations"])


class LiveResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"] = "ok"
    service: Literal["swim-coach-api"] = "swim-coach-api"


class ReadyChecks(BaseModel):
    model_config = ConfigDict(extra="forbid")

    application: Literal["ready"] = "ready"
    database: Literal["ready"] = "ready"


class ReadyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ready"] = "ready"
    checks: ReadyChecks = ReadyChecks()


@router.get("/live", response_model=LiveResponse)
async def live() -> LiveResponse:
    """Report that the API process can serve requests."""

    return LiveResponse()


@router.get("/ready", response_model=ReadyResponse)
async def ready(request: Request) -> ReadyResponse:
    """Report readiness only after PostgreSQL responds."""

    database = request.app.state.services.database
    try:
        await database.ping()
    except Exception as exc:
        raise DomainError("DATABASE_UNAVAILABLE", "The database is not ready.") from exc
    return ReadyResponse()
