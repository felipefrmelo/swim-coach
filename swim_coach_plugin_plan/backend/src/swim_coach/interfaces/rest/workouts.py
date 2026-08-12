"""Canonical workout authoring and local calendar REST API."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Response, status
from pydantic import BaseModel, ConfigDict, Field

from swim_coach.application.services.workouts import WorkoutDetail
from swim_coach.domain.shared.errors import DomainError
from swim_coach.domain.shared.value_objects import EntityId
from swim_coach.domain.workouts import CanonicalWorkout, WorkoutValidationResult, validate_workout
from swim_coach.interfaces.rest.dependencies import (
    Authenticated,
    CsrfAuthenticated,
    RequestCorrelationId,
    Services,
)

router = APIRouter(prefix="/api/v1", tags=["workouts"])
IfMatch = Annotated[str, Header(alias="If-Match")]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WorkoutCreateRequest(StrictModel):
    pool_id: UUID
    definition: CanonicalWorkout


class WorkoutReviseRequest(StrictModel):
    definition: CanonicalWorkout
    change_reason: str | None = Field(default=None, max_length=500)


class WorkoutApproveRequest(StrictModel):
    content_hash: str = Field(min_length=64, max_length=64)


class WorkoutScheduleRequest(StrictModel):
    scheduled_date: date
    scheduled_start_time: time | None = None
    timezone: str = Field(min_length=3, max_length=100)
    pool_id: UUID


class TemplateCreateRequest(StrictModel):
    name: str = Field(min_length=1, max_length=160)
    objective: str = Field(min_length=1, max_length=500)
    definition: CanonicalWorkout


class ScheduleResponse(StrictModel):
    id: UUID
    scheduled_date: date
    scheduled_start_time: time | None
    timezone: str
    pool_id: UUID


class RevisionResponse(StrictModel):
    id: UUID
    revision_number: int
    definition: CanonicalWorkout
    validation: WorkoutValidationResult
    content_hash: str
    change_reason: str | None
    created_at: datetime


class WorkoutResponse(StrictModel):
    id: UUID
    title: str
    purpose: str
    pool_id: UUID
    status: str
    version: int
    current_revision_id: UUID
    approved_revision_id: UUID | None
    current_revision: RevisionResponse
    revisions: list[RevisionResponse]
    schedule: ScheduleResponse | None

    @classmethod
    def from_detail(cls, detail: WorkoutDetail) -> WorkoutResponse:
        workout = detail.workout
        if workout.current_revision_id is None:
            raise DomainError("INTERNAL_ERROR", "Workout current revision is missing.")
        revisions = [
            RevisionResponse(
                id=item.id.value,
                revision_number=item.revision_number,
                definition=item.definition,
                validation=WorkoutValidationResult.model_validate(item.validation),
                content_hash=item.content_hash,
                change_reason=item.change_reason,
                created_at=item.created_at,
            )
            for item in detail.revisions
        ]
        current = next(item for item in revisions if item.id == workout.current_revision_id.value)
        schedule = detail.schedule
        return cls(
            id=workout.id.value,
            title=workout.title,
            purpose=workout.purpose,
            pool_id=workout.pool_id.value,
            status=workout.status.value,
            version=workout.version,
            current_revision_id=workout.current_revision_id.value,
            approved_revision_id=(
                workout.approved_revision_id.value if workout.approved_revision_id else None
            ),
            current_revision=current,
            revisions=revisions,
            schedule=(
                ScheduleResponse(
                    id=schedule.id.value,
                    scheduled_date=schedule.scheduled_date,
                    scheduled_start_time=schedule.scheduled_start_time,
                    timezone=schedule.timezone,
                    pool_id=schedule.pool_id.value,
                )
                if schedule
                else None
            ),
        )


class TemplateResponse(StrictModel):
    id: UUID
    name: str
    objective: str
    tags: list[str]
    definition: CanonicalWorkout
    is_system: bool


def _version(if_match: str) -> int:
    value = if_match.strip().removeprefix("W/").strip('"')
    try:
        version = int(value)
    except ValueError as error:
        raise DomainError(
            "VALIDATION_FAILED", "If-Match must contain the workout version."
        ) from error
    if version < 1:
        raise DomainError("VALIDATION_FAILED", "If-Match must contain a positive version.")
    return version


def _response(detail: WorkoutDetail, response: Response) -> WorkoutResponse:
    response.headers["ETag"] = f'"{detail.workout.version}"'
    return WorkoutResponse.from_detail(detail)


@router.get("/workouts", response_model=list[WorkoutResponse])
async def list_workouts(authenticated: Authenticated, services: Services) -> list[WorkoutResponse]:
    details = await services.workouts.list_workouts(authenticated.user.id)
    return [WorkoutResponse.from_detail(item) for item in details]


@router.post("/workouts", response_model=WorkoutResponse, status_code=status.HTTP_201_CREATED)
async def create_workout(
    payload: WorkoutCreateRequest,
    authenticated: CsrfAuthenticated,
    services: Services,
    correlation_id: RequestCorrelationId,
    response: Response,
) -> WorkoutResponse:
    detail = await services.workouts.create_draft(
        authenticated.user.id,
        payload.definition,
        pool_id=EntityId(payload.pool_id),
        correlation_id=correlation_id,
    )
    return _response(detail, response)


@router.get("/workouts/{workout_id}", response_model=WorkoutResponse)
async def get_workout(
    workout_id: UUID, authenticated: Authenticated, services: Services, response: Response
) -> WorkoutResponse:
    detail = await services.workouts.get_workout(authenticated.user.id, EntityId(workout_id))
    return _response(detail, response)


@router.post("/workouts/{workout_id}/revisions", response_model=WorkoutResponse)
async def revise_workout(
    workout_id: UUID,
    payload: WorkoutReviseRequest,
    if_match: IfMatch,
    authenticated: CsrfAuthenticated,
    services: Services,
    correlation_id: RequestCorrelationId,
    response: Response,
) -> WorkoutResponse:
    detail = await services.workouts.revise(
        authenticated.user.id,
        EntityId(workout_id),
        payload.definition,
        expected_version=_version(if_match),
        change_reason=payload.change_reason,
        correlation_id=correlation_id,
    )
    return _response(detail, response)


@router.post("/workouts/validate", response_model=WorkoutValidationResult)
async def validate_workout_definition(
    definition: CanonicalWorkout, authenticated: Authenticated
) -> WorkoutValidationResult:
    del authenticated
    return validate_workout(definition)


@router.post("/workouts/{workout_id}/approve-local", response_model=WorkoutResponse)
async def approve_workout(
    workout_id: UUID,
    payload: WorkoutApproveRequest,
    if_match: IfMatch,
    authenticated: CsrfAuthenticated,
    services: Services,
    correlation_id: RequestCorrelationId,
    response: Response,
) -> WorkoutResponse:
    detail = await services.workouts.approve_local(
        authenticated.user.id,
        EntityId(workout_id),
        expected_version=_version(if_match),
        expected_content_hash=payload.content_hash,
        correlation_id=correlation_id,
    )
    return _response(detail, response)


@router.post("/workouts/{workout_id}/schedule", response_model=WorkoutResponse)
async def schedule_workout(
    workout_id: UUID,
    payload: WorkoutScheduleRequest,
    if_match: IfMatch,
    authenticated: CsrfAuthenticated,
    services: Services,
    correlation_id: RequestCorrelationId,
    response: Response,
) -> WorkoutResponse:
    detail = await services.workouts.schedule(
        authenticated.user.id,
        EntityId(workout_id),
        scheduled_date=payload.scheduled_date,
        scheduled_start_time=payload.scheduled_start_time,
        timezone=payload.timezone,
        pool_id=EntityId(payload.pool_id),
        expected_version=_version(if_match),
        correlation_id=correlation_id,
    )
    return _response(detail, response)


@router.get("/workout-templates", response_model=list[TemplateResponse])
async def list_templates(
    authenticated: Authenticated, services: Services
) -> list[TemplateResponse]:
    templates = await services.workouts.list_templates(authenticated.user.id)
    return [
        TemplateResponse(
            id=item.id.value,
            name=item.name,
            objective=item.objective,
            tags=list(item.tags),
            definition=item.definition,
            is_system=item.is_system,
        )
        for item in templates
    ]


@router.post(
    "/workout-templates", response_model=TemplateResponse, status_code=status.HTTP_201_CREATED
)
async def create_template(
    payload: TemplateCreateRequest,
    authenticated: CsrfAuthenticated,
    services: Services,
) -> TemplateResponse:
    item = await services.workouts.create_template(
        authenticated.user.id,
        payload.definition,
        name=payload.name,
        objective=payload.objective,
    )
    return TemplateResponse(
        id=item.id.value,
        name=item.name,
        objective=item.objective,
        tags=list(item.tags),
        definition=item.definition,
        is_system=item.is_system,
    )
