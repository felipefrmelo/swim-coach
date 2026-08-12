"""RFC 9457 Problem Details and correlation-id handling."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from swim_coach.domain.shared.errors import DomainError
from swim_coach.domain.shared.value_objects import CorrelationId


class ProblemDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    title: str
    status: int
    detail: str
    code: str
    correlation_id: str
    retryable: bool = False
    details: dict[str, str | int | bool] = Field(default_factory=dict)


STATUS_BY_CODE = {
    "AUTH_REQUIRED": 401,
    "TOKEN_INVALID": 403,
    "TOKEN_EXPIRED": 401,
    "ACCOUNT_DISABLED": 403,
    "RESOURCE_NOT_FOUND": 404,
    "VALIDATION_FAILED": 422,
    "REVISION_CONFLICT": 409,
    "IDEMPOTENCY_CONFLICT": 409,
    "DATABASE_UNAVAILABLE": 503,
    "JOB_ALREADY_RUNNING": 409,
    "GARMIN_NOT_CONNECTED": 409,
    "GARMIN_NOT_CONFIGURED": 503,
}


def correlation_id(request: Request) -> CorrelationId:
    value = getattr(request.state, "correlation_id", None)
    return value if isinstance(value, CorrelationId) else CorrelationId.new()


def problem_response(
    request: Request,
    *,
    code: str,
    detail: str,
    status_code: int,
    details: dict[str, str | int | bool] | None = None,
) -> JSONResponse:
    cid = correlation_id(request)
    problem = ProblemDetail(
        type=f"https://swim-coach.local/problems/{code.casefold().replace('_', '-')}",
        title=code.replace("_", " ").title(),
        status=status_code,
        detail=detail,
        code=code,
        correlation_id=str(cid),
        details=details or {},
    )
    return JSONResponse(
        status_code=status_code,
        content=problem.model_dump(mode="json"),
        media_type="application/problem+json",
        headers={"X-Correlation-Id": str(cid)},
    )


def install_problem_handlers(app: FastAPI) -> None:
    @app.middleware("http")
    async def request_context(request: Request, call_next: Any) -> Any:
        supplied = request.headers.get("X-Correlation-Id")
        try:
            cid = CorrelationId.parse(supplied) if supplied else CorrelationId.new()
        except DomainError:
            cid = CorrelationId.new()
        request.state.correlation_id = cid
        response = await call_next(request)
        response.headers["X-Correlation-Id"] = str(cid)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    @app.exception_handler(DomainError)
    async def handle_domain_error(request: Request, error: DomainError) -> JSONResponse:
        return problem_response(
            request,
            code=error.code,
            detail=error.message,
            status_code=STATUS_BY_CODE.get(error.code, 400),
            details=error.details,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        field_count = len(error.errors())
        return problem_response(
            request,
            code="VALIDATION_FAILED",
            detail="The request did not satisfy the API contract.",
            status_code=422,
            details={"field_error_count": field_count},
        )
