"""Controlled, user-scoped P08 MCP writes and action proposal orchestration."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, cast

from swim_coach.application.ports.repositories import UnitOfWorkFactory
from swim_coach.application.services.activity_data import ActivityDataService
from swim_coach.application.services.garmin_publish import GarminActionDetail, GarminPublishService
from swim_coach.application.services.garmin_sync import GarminSyncService
from swim_coach.application.services.mcp_read import McpPrincipal, McpResult
from swim_coach.application.services.planning import PlanningService
from swim_coach.application.services.workouts import WorkoutService
from swim_coach.domain.actions import ActionApproval, ActionDecision, ActionProposal
from swim_coach.domain.operations import (
    ApiIdempotencyRecord,
    AuditEvent,
    Job,
    JobStatus,
    OutboxEvent,
)
from swim_coach.domain.planning import PlanningPreferences
from swim_coach.domain.shared.errors import (
    DomainError,
    ResourceNotFoundError,
    RevisionConflictError,
)
from swim_coach.domain.shared.types import JsonObject
from swim_coach.domain.shared.value_objects import CorrelationId, EntityId
from swim_coach.domain.workouts import CanonicalWorkout, validate_workout

MCP_WRITE_SCOPES = (
    "proposals:read",
    "operations:read",
    "sync:run",
    "feedback:write",
    "workouts:write",
    "garmin:publish",
    "proposals:write",
    "proposals:approve",
    "operations:retry",
)
MCP_WRITE_TOOL_SCOPES: dict[str, tuple[str, ...]] = {
    "get_action_proposal": ("proposals:read",),
    "get_job_status": ("operations:read",),
    "sync_garmin_activities": ("sync:run",),
    "record_session_feedback": ("feedback:write",),
    "create_workout_draft": ("workouts:write",),
    "propose_workout_change": ("workouts:write", "proposals:write"),
    "propose_workout_reschedule": ("workouts:write", "proposals:write"),
    "preview_garmin_publish": ("garmin:publish", "proposals:write"),
    "cancel_action_proposal": ("proposals:write",),
    "approve_action_proposal": ("proposals:approve",),
    "execute_approved_action": ("proposals:approve",),
    "retry_failed_job": ("operations:retry",),
}
MCP_PLANNING_TOOL_SCOPES: dict[str, tuple[str, ...]] = {
    "propose_week_plan": ("planning:write", "proposals:write"),
}
MCP_WRITE_TOOLS = tuple(MCP_WRITE_TOOL_SCOPES)
MCP_PLANNING_TOOLS = tuple(MCP_PLANNING_TOOL_SCOPES)


class McpWriteService:
    CHANGE_ACTION = "workout.change.v1"
    RESCHEDULE_ACTION = "workout.reschedule.v1"

    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory,
        workouts: WorkoutService,
        activity_data: ActivityDataService,
        garmin_sync: GarminSyncService | None,
        garmin_publish: GarminPublishService,
        planning: PlanningService | None,
    ) -> None:
        self._uow_factory = uow_factory
        self._workouts = workouts
        self._activity_data = activity_data
        self._garmin_sync = garmin_sync
        self._garmin_publish = garmin_publish
        self._planning = planning

    @property
    def garmin_write_enabled(self) -> bool:
        return self._garmin_publish.write_enabled

    @property
    def planning_enabled(self) -> bool:
        return self._planning is not None

    async def propose_week_plan(
        self,
        principal: McpPrincipal,
        request_id: str,
        *,
        week_start: date,
        constraints: dict[str, Any],
        user_notes: str | None,
        correlation_id: CorrelationId,
    ) -> McpResult:
        if self._planning is None:
            raise DomainError("PLANNING_DISABLED", "Adaptive weekly planning is disabled.")
        preferences = PlanningPreferences.model_validate(constraints)
        run, proposal, replayed = await self._planning.propose_week(
            principal.user_id,
            actor_id=principal.subject,
            week_start=week_start,
            preferences=preferences,
            user_notes_present=bool(user_notes and user_notes.strip()),
            correlation_id=correlation_id,
        )
        week = run.output_plan
        return McpResult(
            request_id=request_id,
            status="OK",
            data={
                "planning_run_id": str(run.id),
                "proposal_id": str(proposal.id),
                "action_type": proposal.action_type,
                "status": proposal.status.value,
                "action_hash": proposal.action_hash,
                "expires_at": proposal.expires_at.isoformat(),
                "required_action_scope": "planning:write",
                "input_hash": run.input_hash,
                "replayed": replayed,
                "week": week,
                "impact": proposal.impact,
                "execution": None,
            },
            human_summary=(
                "Generated a reproducible weekly plan proposal for review. No workout, "
                "calendar entry, approval, execution, or Garmin state was changed."
            ),
        )

    async def get_action_proposal(
        self, principal: McpPrincipal, request_id: str, proposal_id: EntityId
    ) -> McpResult:
        detail = await self._proposal_detail(principal, proposal_id)
        return self._proposal_result(request_id, detail)

    async def get_job_status(
        self, principal: McpPrincipal, request_id: str, job_id: EntityId
    ) -> McpResult:
        async with self._uow_factory() as uow:
            job = await uow.jobs.get(principal.user_id, job_id)
        if job is None:
            raise ResourceNotFoundError("job")
        retryable = bool(
            job.status is JobStatus.FAILED_TERMINAL
            and job.last_error
            and job.last_error.get("retryable")
            and not job.last_error.get("ambiguous_external_effect")
        )
        return McpResult(
            request_id=request_id,
            status="OK",
            data={
                "job_id": str(job.id),
                "job_type": job.job_type,
                "status": job.status.value,
                "attempts": job.attempts,
                "max_attempts": job.max_attempts,
                "retryable": retryable,
                "result_references": self._safe_job_references(job.payload),
                "error": self._safe_error(job.last_error),
            },
            human_summary=f"Background job is {job.status.value} after {job.attempts} attempt(s).",
        )

    async def sync_garmin_activities(
        self,
        principal: McpPrincipal,
        request_id: str,
        *,
        from_date: date | None,
        force: bool,
        idempotency_key: str,
    ) -> McpResult:
        if self._garmin_sync is None:
            raise DomainError("GARMIN_SYNC_DISABLED", "Garmin synchronization is disabled.")
        job = await self._garmin_sync.request_sync(
            principal.user_id,
            idempotency_key,
            from_date=from_date,
            force=force,
        )
        return McpResult(
            request_id=request_id,
            status="OK",
            data={
                "job_id": str(job.id),
                "status": job.status.value,
                "queued": True,
                "from_date": from_date.isoformat() if from_date else None,
                "force": force,
            },
            human_summary="Garmin activity synchronization was queued idempotently.",
        )

    async def record_session_feedback(
        self,
        principal: McpPrincipal,
        request_id: str,
        *,
        activity_id: EntityId,
        rpe: int,
        technique: str,
        pain: dict[str, Any],
        notes: str | None,
        idempotency_key: str,
        correlation_id: CorrelationId,
    ) -> McpResult:
        technique_rating = self._rating(technique, "technique")
        pain_present = bool(pain.get("present", False))
        pain_intensity_raw = pain.get("intensity")
        pain_intensity = int(pain_intensity_raw) if pain_intensity_raw is not None else None
        if pain_intensity is not None and not 1 <= pain_intensity <= 10:
            raise DomainError("VALIDATION_FAILED", "pain.intensity must be between 1 and 10.")
        request_hash = hashlib.sha256(
            json.dumps(
                {
                    "activity_id": str(activity_id),
                    "rpe": rpe,
                    "technique_rating": technique_rating,
                    "pain": pain,
                    "notes": notes,
                },
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode()
        ).hexdigest()
        feedback = await self._activity_data.record_feedback(
            principal.user_id,
            activity_id,
            rpe=rpe,
            technique_rating=technique_rating,
            fatigue_rating=None,
            enjoyment_rating=None,
            pain_present=pain_present,
            pain_location=(str(pain.get("location"))[:160] if pain.get("location") else None),
            pain_intensity=pain_intensity,
            comment=notes,
            expected_version=None,
            actor_id=principal.subject,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )
        return McpResult(
            request_id=request_id,
            status="OK",
            data={
                "activity_id": str(activity_id),
                "feedback_id": str(feedback.id),
                "version": feedback.version,
                "pain_present": feedback.pain_present,
            },
            human_summary="Post-swim feedback was stored locally.",
        )

    async def create_workout_draft(
        self,
        principal: McpPrincipal,
        request_id: str,
        *,
        definition: CanonicalWorkout,
        pool_id: EntityId | None,
        correlation_id: CorrelationId,
    ) -> McpResult:
        selected_pool_id = pool_id
        if selected_pool_id is None:
            async with self._uow_factory() as uow:
                pools = await uow.pools.list(principal.user_id)
            selected = next(
                (pool for pool in pools if pool.is_default and pool.active),
                next((pool for pool in pools if pool.active), None),
            )
            if selected is None:
                raise DomainError("POOL_REQUIRED", "Configure a pool before creating a workout.")
            selected_pool_id = selected.id
        detail = await self._workouts.create_draft(
            principal.user_id,
            definition,
            pool_id=selected_pool_id,
            correlation_id=correlation_id,
        )
        return McpResult(
            request_id=request_id,
            status="OK",
            data={
                "workout_id": str(detail.workout.id),
                "revision": detail.current_revision.revision_number,
                "content_hash": detail.current_revision.content_hash,
                "status": detail.workout.status.value,
            },
            human_summary=f"Created local draft {detail.workout.title}.",
        )

    async def propose_workout_change(
        self,
        principal: McpPrincipal,
        request_id: str,
        *,
        workout_id: EntityId,
        expected_revision: int,
        change_request: dict[str, Any],
        correlation_id: CorrelationId,
    ) -> McpResult:
        detail = await self._workouts.get_workout(principal.user_id, workout_id)
        if detail.current_revision.revision_number != expected_revision:
            raise RevisionConflictError(detail.workout.version)
        raw_definition = change_request.get("definition")
        if not isinstance(raw_definition, dict):
            raise DomainError(
                "VALIDATION_FAILED", "change_request.definition must contain a full workout."
            )
        definition = CanonicalWorkout.model_validate(raw_definition)
        validation = validate_workout(definition)
        if not validation.valid:
            raise DomainError("VALIDATION_FAILED", "The proposed workout definition is invalid.")
        proposal = await self._create_local_proposal(
            principal,
            action_type=self.CHANGE_ACTION,
            detail=detail,
            payload=cast(
                JsonObject,
                {
                    "definition": definition.model_dump(mode="json"),
                    "expected_workout_version": detail.workout.version,
                    "change_reason": str(change_request.get("reason") or "MCP proposal")[:500],
                },
            ),
            impact=cast(
                JsonObject,
                {
                    "before": {
                        "title": detail.workout.title,
                        "distance_m": detail.current_revision.totals.distance_m,
                    },
                    "after": {
                        "title": definition.title,
                        "distance_m": validation.totals.distance_m,
                    },
                    "external_effects": [],
                },
            ),
            correlation_id=correlation_id,
        )
        return self._proposal_result(request_id, GarminActionDetail(proposal, None))

    async def propose_workout_reschedule(
        self,
        principal: McpPrincipal,
        request_id: str,
        *,
        workout_id: EntityId,
        new_date: date,
        local_time: time | None,
        correlation_id: CorrelationId,
    ) -> McpResult:
        detail = await self._workouts.get_workout(principal.user_id, workout_id)
        if detail.schedule is None:
            raise DomainError("SCHEDULE_REQUIRED", "The workout must already be scheduled.")
        proposal = await self._create_local_proposal(
            principal,
            action_type=self.RESCHEDULE_ACTION,
            detail=detail,
            payload=cast(
                JsonObject,
                {
                    "new_date": new_date.isoformat(),
                    "local_time": local_time.isoformat() if local_time else None,
                    "timezone": detail.schedule.timezone,
                    "pool_id": str(detail.schedule.pool_id),
                    "expected_workout_version": detail.workout.version,
                },
            ),
            impact=cast(
                JsonObject,
                {
                    "before_date": detail.schedule.scheduled_date.isoformat(),
                    "after_date": new_date.isoformat(),
                    "recovery_warning": "Review adjacent sessions before approval.",
                    "external_effects": [],
                },
            ),
            correlation_id=correlation_id,
        )
        return self._proposal_result(request_id, GarminActionDetail(proposal, None))

    async def preview_garmin_publish(
        self,
        principal: McpPrincipal,
        request_id: str,
        *,
        workout_id: EntityId,
        revision: int,
        schedule_date: date,
        target_device_id: EntityId | None,
        correlation_id: CorrelationId,
    ) -> McpResult:
        workout = await self._workouts.get_workout(principal.user_id, workout_id)
        if workout.current_revision.revision_number != revision:
            raise RevisionConflictError(workout.workout.version)
        if workout.schedule is None or workout.schedule.scheduled_date != schedule_date:
            raise DomainError("REVISION_CONFLICT", "The requested schedule date is not current.")
        detail = await self._garmin_publish.preview(
            principal.user_id,
            workout_id,
            expected_workout_version=workout.workout.version,
            device_id=target_device_id,
            correlation_id=correlation_id,
        )
        return self._proposal_result(request_id, detail)

    async def cancel_action_proposal(
        self,
        principal: McpPrincipal,
        request_id: str,
        *,
        proposal_id: EntityId,
        reason: str | None,
        correlation_id: CorrelationId,
    ) -> McpResult:
        now = datetime.now(UTC)
        async with self._uow_factory() as uow:
            proposal = await uow.action_proposals.get_for_update(principal.user_id, proposal_id)
            if proposal is None:
                raise ResourceNotFoundError("action_proposal")
            previous_version = proposal.version
            proposal.cancel(now)
            await uow.action_proposals.update(proposal, expected_version=previous_version)
            await self._record_proposal(
                uow,
                proposal,
                correlation_id,
                "swim_coach.actions.cancelled.v1",
                "actions.cancelled",
                metadata={"reason_recorded": bool(reason)},
            )
            await uow.commit()
        result = self._proposal_result(request_id, GarminActionDetail(proposal, None))
        result.data["reason_recorded"] = bool(reason)
        return result

    async def approve_action_proposal(
        self,
        principal: McpPrincipal,
        request_id: str,
        *,
        proposal_id: EntityId,
        expected_action_hash: str,
        decision: str,
        confirmation_text: str,
        correlation_id: CorrelationId,
    ) -> McpResult:
        if not confirmation_text.strip():
            raise DomainError("CONFIRMATION_REQUIRED", "Explicit confirmation text is required.")
        detail = await self._proposal_detail(principal, proposal_id)
        proposal = detail.proposal
        if proposal.action_type == GarminPublishService.ACTION_TYPE:
            if decision == ActionDecision.REJECT.value:
                garmin_detail = await self._garmin_publish.reject(
                    principal.user_id,
                    proposal.id,
                    expected_version=proposal.version,
                    action_hash=expected_action_hash,
                    correlation_id=correlation_id,
                )
            elif decision == ActionDecision.APPROVE.value:
                garmin_detail = await self._garmin_publish.approve(
                    principal.user_id,
                    proposal.id,
                    expected_version=proposal.version,
                    action_hash=expected_action_hash,
                    correlation_id=correlation_id,
                    explicit_verb=confirmation_text,
                )
            else:
                raise DomainError("VALIDATION_FAILED", "decision must be APPROVE or REJECT.")
            return self._proposal_result(request_id, garmin_detail)
        local_proposal = await self._decide_local(
            principal,
            proposal,
            expected_action_hash=expected_action_hash,
            decision=decision,
            confirmation_text=confirmation_text,
            correlation_id=correlation_id,
        )
        return self._proposal_result(request_id, GarminActionDetail(local_proposal, None))

    async def execute_approved_action(
        self,
        principal: McpPrincipal,
        request_id: str,
        *,
        proposal_id: EntityId,
        idempotency_key: str,
        correlation_id: CorrelationId,
    ) -> McpResult:
        detail = await self._proposal_detail(principal, proposal_id)
        proposal = detail.proposal
        required_scope = self.required_action_scope(proposal.action_type)
        if required_scope not in principal.scopes:
            raise DomainError(
                "SCOPE_REQUIRED",
                "The approved action requires an additional action-specific scope.",
                details={"scope": required_scope},
            )
        if proposal.action_type != GarminPublishService.ACTION_TYPE:
            raise DomainError(
                "ACTION_EXECUTION_UNAVAILABLE",
                "This local proposal is reviewable in P08 but execution remains disabled.",
            )
        queued = await self._garmin_publish.execute(
            principal.user_id,
            proposal.id,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )
        result = self._proposal_result(request_id, queued)
        if queued.execution:
            async with self._uow_factory() as uow:
                job = await uow.jobs.get_by_idempotency_key(queued.execution.idempotency_key)
            result.data["job_id"] = str(job.id) if job else None
        return result

    async def retry_failed_job(
        self,
        principal: McpPrincipal,
        request_id: str,
        *,
        job_id: EntityId,
        idempotency_key: str,
        correlation_id: CorrelationId,
    ) -> McpResult:
        now = datetime.now(UTC)
        scope = f"mcp-job-retry:{principal.user_id}:{job_id}"
        request_hash = hashlib.sha256(str(job_id).encode()).hexdigest()
        async with self._uow_factory() as uow:
            replay = await uow.idempotency.get(scope, idempotency_key, now)
            if replay is not None:
                if replay.request_hash != request_hash:
                    raise DomainError(
                        "IDEMPOTENCY_CONFLICT",
                        "This idempotency key was already used for another retry.",
                    )
                replayed_job = await uow.jobs.get(principal.user_id, job_id)
                if replayed_job is None:
                    raise ResourceNotFoundError("job")
                return self._job_result(request_id, replayed_job, replayed=True)
            job = await uow.jobs.get(principal.user_id, job_id)
            if job is None:
                raise ResourceNotFoundError("job")
            if (
                job.status is not JobStatus.FAILED_TERMINAL
                or not job.last_error
                or not bool(job.last_error.get("retryable"))
                or bool(job.last_error.get("ambiguous_external_effect"))
            ):
                raise DomainError(
                    "JOB_NOT_RETRYABLE", "The job is not classified as safely retryable."
                )
            retried = await uow.jobs.retry_failed(principal.user_id, job_id, now)
            if retried is None:
                raise DomainError("JOB_STATE_CONFLICT", "The job state changed before retry.")
            await uow.idempotency.add(
                ApiIdempotencyRecord(
                    scope=scope,
                    idempotency_key=idempotency_key,
                    request_hash=request_hash,
                    response_status=200,
                    response={"resource_id": str(job_id)},
                    created_at=now,
                    expires_at=now + timedelta(hours=24),
                )
            )
            await uow.audit.add(
                AuditEvent(
                    id=EntityId.new(),
                    user_id=principal.user_id,
                    actor_type="mcp",
                    actor_id=principal.subject,
                    action="operations.job_retry_queued",
                    entity_type="Job",
                    entity_id=job_id,
                    correlation_id=correlation_id,
                    after={"job_id": str(job_id), "status": retried.status.value},
                )
            )
            await uow.outbox.add(
                OutboxEvent(
                    id=EntityId.new(),
                    aggregate_type="Job",
                    aggregate_id=job_id,
                    event_type="swim_coach.operations.job_retry_queued.v1",
                    payload={"job_id": str(job_id), "status": retried.status.value},
                    user_id=principal.user_id,
                    correlation_id=correlation_id,
                )
            )
            await uow.commit()
        return self._job_result(request_id, retried, replayed=False)

    @staticmethod
    def required_action_scope(action_type: str) -> str:
        if action_type == GarminPublishService.ACTION_TYPE:
            return "garmin:publish"
        if action_type == PlanningService.ACTION_TYPE:
            return "planning:write"
        return "workouts:write"

    async def _proposal_detail(
        self, principal: McpPrincipal, proposal_id: EntityId
    ) -> GarminActionDetail:
        async with self._uow_factory() as uow:
            proposal = await uow.action_proposals.get(principal.user_id, proposal_id)
            if proposal is None:
                raise ResourceNotFoundError("action_proposal")
            execution = await uow.action_executions.get_by_proposal(principal.user_id, proposal.id)
        return GarminActionDetail(proposal, execution)

    async def _create_local_proposal(
        self,
        principal: McpPrincipal,
        *,
        action_type: str,
        detail: Any,
        payload: JsonObject,
        impact: JsonObject,
        correlation_id: CorrelationId,
    ) -> ActionProposal:
        now = datetime.now(UTC)
        proposal = ActionProposal.ready_for_review(
            id=EntityId.new(),
            user_id=principal.user_id,
            action_type=action_type,
            target_type="planned_workout",
            target_id=detail.workout.id,
            target_revision_id=detail.current_revision.id,
            payload=payload,
            impact=impact,
            expires_at=now.replace(microsecond=0) + timedelta(minutes=30),
            created_at=now.replace(microsecond=0),
        )
        async with self._uow_factory() as uow:
            existing = await uow.action_proposals.get_by_hash(
                principal.user_id, proposal.action_hash
            )
            if existing is not None:
                return existing
            await uow.action_proposals.add(proposal)
            await self._record_proposal(
                uow,
                proposal,
                correlation_id,
                "swim_coach.actions.local_proposed.v1",
                "actions.local_proposed",
            )
            await uow.commit()
        return proposal

    async def _decide_local(
        self,
        principal: McpPrincipal,
        proposal: ActionProposal,
        *,
        expected_action_hash: str,
        decision: str,
        confirmation_text: str,
        correlation_id: CorrelationId,
    ) -> ActionProposal:
        now = datetime.now(UTC)
        async with self._uow_factory() as uow:
            current = await uow.action_proposals.get_for_update(principal.user_id, proposal.id)
            if current is None:
                raise ResourceNotFoundError("action_proposal")
            previous_version = current.version
            if decision == ActionDecision.APPROVE.value:
                current.approve(action_hash=expected_action_hash, now=now)
                selected = ActionDecision.APPROVE
            elif decision == ActionDecision.REJECT.value:
                current.reject(action_hash=expected_action_hash, now=now)
                selected = ActionDecision.REJECT
            else:
                raise DomainError("VALIDATION_FAILED", "decision must be APPROVE or REJECT.")
            await uow.action_approvals.add(
                ActionApproval(
                    id=EntityId.new(),
                    proposal_id=current.id,
                    user_id=principal.user_id,
                    action_hash=current.action_hash,
                    decision=selected,
                    explicit_verb=confirmation_text.strip()[:200],
                    created_at=now,
                )
            )
            await uow.action_proposals.update(current, expected_version=previous_version)
            await self._record_proposal(
                uow,
                current,
                correlation_id,
                "swim_coach.actions.local_decided.v1",
                "actions.local_decided",
            )
            await uow.commit()
        return current

    @staticmethod
    def _proposal_result(request_id: str, detail: GarminActionDetail) -> McpResult:
        proposal = detail.proposal
        execution = detail.execution
        return McpResult(
            request_id=request_id,
            status="OK",
            data={
                "proposal_id": str(proposal.id),
                "action_type": proposal.action_type,
                "status": proposal.status.value,
                "version": proposal.version,
                "action_hash": proposal.action_hash,
                "expires_at": proposal.expires_at.isoformat(),
                "required_action_scope": McpWriteService.required_action_scope(
                    proposal.action_type
                ),
                "impact": proposal.impact,
                "execution": (
                    {
                        "execution_id": str(execution.id),
                        "status": execution.status.value,
                        "result": execution.result,
                        "error": McpWriteService._safe_error(execution.error),
                    }
                    if execution
                    else None
                ),
            },
            human_summary=(
                f"Action proposal is {proposal.status.value}; review its exact hash and impact."
            ),
        )

    @staticmethod
    async def _record_proposal(
        uow: Any,
        proposal: ActionProposal,
        correlation_id: CorrelationId,
        event_type: str,
        action: str,
        metadata: JsonObject | None = None,
    ) -> None:
        payload: JsonObject = {
            "proposal_id": str(proposal.id),
            "action_hash": proposal.action_hash,
            "status": proposal.status.value,
            "version": proposal.version,
            **(metadata or {}),
        }
        await uow.outbox.add(
            OutboxEvent(
                id=EntityId.new(),
                aggregate_type="ActionProposal",
                aggregate_id=proposal.id,
                aggregate_version=proposal.version,
                event_type=event_type,
                payload=payload,
                user_id=proposal.user_id,
                correlation_id=correlation_id,
            )
        )
        await uow.audit.add(
            AuditEvent(
                id=EntityId.new(),
                user_id=proposal.user_id,
                actor_type="mcp",
                actor_id=str(proposal.user_id),
                action=action,
                entity_type="ActionProposal",
                entity_id=proposal.id,
                correlation_id=correlation_id,
                after=payload,
            )
        )

    @staticmethod
    def _rating(value: str, field: str) -> int:
        labels = {"poor": 1, "fair": 2, "ok": 3, "good": 4, "excellent": 5}
        normalized = value.strip().casefold()
        try:
            rating = int(normalized)
        except ValueError:
            rating = labels.get(normalized, 0)
        if not 1 <= rating <= 5:
            raise DomainError(
                "VALIDATION_FAILED", f"{field} must be 1-5 or poor/fair/ok/good/excellent."
            )
        return rating

    @staticmethod
    def _safe_error(error: JsonObject | None) -> JsonObject | None:
        if not error:
            return None
        return cast(
            JsonObject,
            {
                key: error[key]
                for key in ("code", "message", "retryable", "category")
                if key in error
            },
        )

    @staticmethod
    def _safe_job_references(payload: JsonObject) -> JsonObject:
        return cast(
            JsonObject,
            {
                key: value
                for key, value in payload.items()
                if key in {"proposal_id", "execution_id", "binding_id"}
            },
        )

    @staticmethod
    def _job_result(request_id: str, job: Job, *, replayed: bool) -> McpResult:
        queued = job.status in {JobStatus.QUEUED, JobStatus.RETRY_SCHEDULED}
        return McpResult(
            request_id=request_id,
            status="OK",
            data={
                "job_id": str(job.id),
                "status": job.status.value,
                "retry_queued": queued,
                "replayed": replayed,
            },
            human_summary=(
                "The safe failed job is queued for retry."
                if queued
                else f"The previously requested retry is now {job.status.value}."
            ),
        )

    @staticmethod
    def stable_idempotency_key(prefix: str, raw: str) -> str:
        return f"{prefix}:{hashlib.sha256(raw.strip().encode()).hexdigest()}"
