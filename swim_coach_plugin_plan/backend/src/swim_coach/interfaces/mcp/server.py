"""Authenticated, read-only P05 MCP server."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from datetime import date as LocalDate
from datetime import datetime, time
from time import perf_counter
from typing import Annotated, Any, Literal
from uuid import UUID

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.fastmcp.server import Settings as FastMCPSettings
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import AnyHttpUrl, Field

from swim_coach.application.queries.get_capabilities import (
    CapabilityResult,
)
from swim_coach.application.queries.get_capabilities import (
    get_capabilities as p00_capabilities,
)
from swim_coach.application.services.mcp_read import McpPrincipal, McpReadService, McpResult
from swim_coach.application.services.mcp_write import McpWriteService
from swim_coach.domain.shared.errors import DomainError
from swim_coach.domain.shared.value_objects import CorrelationId, EntityId
from swim_coach.domain.workouts import CanonicalWorkout

READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)
LOCAL_WRITE = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=False,
    openWorldHint=False,
)
OPEN_WORLD_WRITE = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=True,
)
DESTRUCTIVE_LOCAL_WRITE = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=True,
    openWorldHint=False,
)


def create_mcp_server(
    *,
    read_service: McpReadService | None = None,
    write_service: McpWriteService | None = None,
    token_verifier: TokenVerifier | None = None,
    oauth_issuer: str | None = None,
    oauth_resource: str | None = None,
    allowed_hosts: list[str] | None = None,
    allowed_origins: list[str] | None = None,
) -> FastMCP:
    """Create a fail-closed read server; private tools exist only with OAuth configured."""

    FastMCPSettings.model_rebuild(_types_namespace={"FastMCP": FastMCP})
    oauth_enabled = bool(read_service and token_verifier and oauth_issuer and oauth_resource)
    auth: AuthSettings | None = None
    if oauth_enabled:
        if oauth_issuer is None or oauth_resource is None:
            raise RuntimeError("OAuth MCP configuration is incomplete")
        auth = AuthSettings(
            issuer_url=AnyHttpUrl(oauth_issuer),
            resource_server_url=AnyHttpUrl(oauth_resource),
            required_scopes=[],
        )
    write_enabled = bool(oauth_enabled and write_service)
    instructions = (
        "Swim Coach exposes authenticated, user-scoped swimming training data. "
        + (
            "Controlled write tools are enabled. Preview never approves or executes. Approval "
            "must contain the exact persisted hash after a user-visible review, and execution "
            "must happen only in a later explicit user turn. Never combine preview, approval, "
            "and execution into one response or infer confirmation."
            if write_enabled
            else (
                "All available tools are read-only and use local persisted data. Never imply "
                "that a tool synced Garmin, changed a workout, scheduled anything, or performed "
                "an external effect."
            )
        )
        if oauth_enabled
        else (
            "OAuth is not configured. Only the harmless public capability check is available; "
            "do not infer private-data or product readiness."
        )
    )
    server = FastMCP(
        name="swim-coach",
        instructions=instructions,
        streamable_http_path="/",
        json_response=True,
        stateless_http=True,
        auth=auth,
        token_verifier=token_verifier if oauth_enabled else None,
        max_request_body_size=128 * 1024,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=allowed_hosts or ["127.0.0.1", "127.0.0.1:*", "localhost", "localhost:*"],
            allowed_origins=allowed_origins or ["http://127.0.0.1:*", "http://localhost:*"],
        ),
    )

    if not oauth_enabled:
        _register_p00_capabilities(server)
        _harden_tool_schemas(server)
        return server
    if read_service is None:  # Defensive; oauth_enabled already guarantees this.
        raise RuntimeError("MCP read service is missing")

    async def execute(
        tool_name: str,
        ctx: Context[Any, Any, Any],
        required_scopes: frozenset[str],
        arguments: dict[str, Any],
        query: Callable[[McpPrincipal, str], Awaitable[McpResult]],
    ) -> McpResult:
        request_id = _safe_request_id(ctx.request_id)
        access_token = get_access_token()
        if access_token is None or not access_token.subject:
            raise ToolError(
                _error("AUTH_REQUIRED", "OAuth authentication is required.", request_id)
            )
        principal: McpPrincipal | None = None
        started_at = perf_counter()
        try:
            principal = await read_service.resolve_principal(
                subject=access_token.subject,
                scopes=access_token.scopes,
                required_scopes=required_scopes,
            )
            result = await query(principal, request_id)
            await read_service.record_invocation(
                principal=principal,
                tool_name=tool_name,
                request_id=request_id,
                arguments=arguments,
                started_at=started_at,
                outcome=result.status
                if result.status in {"OK", "NOT_FOUND", "PARTIAL"}
                else "FAILED",
            )
            return result
        except DomainError as error:
            if principal is not None:
                await read_service.record_invocation(
                    principal=principal,
                    tool_name=tool_name,
                    request_id=request_id,
                    arguments=arguments,
                    started_at=started_at,
                    outcome="NOT_FOUND" if error.code == "RESOURCE_NOT_FOUND" else "FAILED",
                    error_code=error.code,
                )
            raise ToolError(_error(error.code, error.message, request_id, error.details)) from error

    async def execute_write(
        tool_name: str,
        ctx: Context[Any, Any, Any],
        required_scopes: frozenset[str],
        arguments: dict[str, Any],
        command: Callable[[McpPrincipal, str, CorrelationId], Awaitable[McpResult]],
    ) -> McpResult:
        if write_service is None:
            raise ToolError(
                _error(
                    "MCP_WRITE_DISABLED",
                    "MCP writes are disabled by the server kill switch.",
                    _safe_request_id(ctx.request_id),
                )
            )
        request_id = _safe_request_id(ctx.request_id)
        access_token = get_access_token()
        if access_token is None or not access_token.subject:
            raise ToolError(
                _error("AUTH_REQUIRED", "OAuth authentication is required.", request_id)
            )
        principal: McpPrincipal | None = None
        correlation_id = CorrelationId.new()
        started_at = perf_counter()
        try:
            principal = await read_service.resolve_principal(
                subject=access_token.subject,
                scopes=access_token.scopes,
                required_scopes=required_scopes,
            )
            result = await command(principal, request_id, correlation_id)
            causation_id = _result_causation(result)
            await read_service.record_invocation(
                principal=principal,
                tool_name=tool_name,
                request_id=request_id,
                arguments=arguments,
                started_at=started_at,
                outcome=result.status,
                correlation_id=correlation_id,
                causation_id=causation_id,
            )
            return result
        except DomainError as error:
            if principal is not None:
                await read_service.record_invocation(
                    principal=principal,
                    tool_name=tool_name,
                    request_id=request_id,
                    arguments=arguments,
                    started_at=started_at,
                    outcome="NOT_FOUND" if error.code == "RESOURCE_NOT_FOUND" else "FAILED",
                    correlation_id=correlation_id,
                    causation_id=_argument_causation(arguments),
                    error_code=error.code,
                )
            raise ToolError(_error(error.code, error.message, request_id, error.details)) from error

    @server.tool(
        name="get_capabilities",
        title="Get Swim Coach capabilities",
        description="Return enabled read-only workflows, scopes, versions, and limitations.",
        annotations=READ_ONLY,
        structured_output=True,
    )
    async def get_capabilities(ctx: Context[Any, Any, Any]) -> McpResult:
        async def query(_: McpPrincipal, request_id: str) -> McpResult:
            result = await read_service.get_capabilities(request_id)
            if write_enabled and write_service is not None:
                from swim_coach.application.services.mcp_write import (
                    MCP_WRITE_SCOPES,
                    MCP_WRITE_TOOLS,
                )

                result.data["server_version"] = "0.2.0-controlled-write"
                result.data["phase"] = "P08"
                result.data["release_mode"] = "authenticated-controlled-write"
                result.data["available_tools"] = [*result.data["available_tools"], *MCP_WRITE_TOOLS]
                result.data["required_scopes"] = [
                    *result.data["required_scopes"],
                    *MCP_WRITE_SCOPES,
                ]
                result.data["garmin_sync_via_tool_enabled"] = True
                result.data["garmin_write_enabled"] = write_service.garmin_write_enabled
                result.human_summary = (
                    "Swim Coach exposes authenticated reads and controlled writes with exact-hash "
                    "approval and a separate execution turn."
                )
            return result

        return await execute(
            "get_capabilities",
            ctx,
            frozenset(),
            {},
            query,
        )

    @server.tool(
        name="get_training_context",
        title="Get training context",
        description=(
            "Return the authenticated athlete's pool, active goal, availability, "
            "constraints, and current training summary."
        ),
        annotations=READ_ONLY,
        structured_output=True,
    )
    async def get_training_context(
        ctx: Context[Any, Any, Any], include_constraints: bool = True
    ) -> McpResult:
        args = {"include_constraints": include_constraints}
        return await execute(
            "get_training_context",
            ctx,
            frozenset({"profile:read", "goals:read"}),
            args,
            lambda principal, request_id: read_service.get_training_context(
                principal, request_id, include_constraints=include_constraints
            ),
        )

    @server.tool(
        name="get_today_workout",
        title="Get today's swim workout",
        description=(
            "Return a planned pool workout for a date in the athlete's configured timezone."
        ),
        annotations=READ_ONLY,
        structured_output=True,
    )
    async def get_today_workout(
        ctx: Context[Any, Any, Any],
        date: LocalDate | None = None,
        include_steps: bool = True,
        include_publish_status: bool = True,
    ) -> McpResult:
        args = {
            "date": date.isoformat() if date else None,
            "include_steps": include_steps,
            "include_publish_status": include_publish_status,
        }
        return await execute(
            "get_today_workout",
            ctx,
            frozenset({"workouts:read"}),
            args,
            lambda principal, request_id: read_service.get_today_workout(
                principal,
                request_id,
                target_date=date,
                include_steps=include_steps,
                include_publish_status=include_publish_status,
            ),
        )

    @server.tool(
        name="get_week_plan",
        title="Get weekly swim plan",
        description=(
            "Return planned sessions, volume, objectives, statuses, and warnings for a week."
        ),
        annotations=READ_ONLY,
        structured_output=True,
    )
    async def get_week_plan(
        ctx: Context[Any, Any, Any], week_start: LocalDate | None = None
    ) -> McpResult:
        args = {"week_start": week_start.isoformat() if week_start else None}
        return await execute(
            "get_week_plan",
            ctx,
            frozenset({"workouts:read"}),
            args,
            lambda principal, request_id: read_service.get_week_plan(
                principal, request_id, week_start=week_start
            ),
        )

    @server.tool(
        name="list_recent_swims",
        title="List recent pool swims",
        description=(
            "List recent locally persisted pool swims with concise analysis summaries "
            "and bounded pagination."
        ),
        annotations=READ_ONLY,
        structured_output=True,
    )
    async def list_recent_swims(
        ctx: Context[Any, Any, Any],
        limit: Annotated[int, Field(ge=1, le=20)] = 5,
        before: datetime | None = None,
        include_analysis_summary: bool = True,
    ) -> McpResult:
        if not 1 <= limit <= 20:
            raise ToolError(
                _error(
                    "VALIDATION_FAILED",
                    "limit must be between 1 and 20.",
                    _safe_request_id(ctx.request_id),
                )
            )
        if before is not None and before.tzinfo is None:
            raise ToolError(
                _error(
                    "VALIDATION_FAILED",
                    "before must include a timezone.",
                    _safe_request_id(ctx.request_id),
                )
            )
        args = {
            "limit": limit,
            "before": before.isoformat() if before else None,
            "include_analysis_summary": include_analysis_summary,
        }
        return await execute(
            "list_recent_swims",
            ctx,
            frozenset({"activities:read"}),
            args,
            lambda principal, request_id: read_service.list_recent_swims(
                principal,
                request_id,
                limit=limit,
                before=before,
                include_analysis_summary=include_analysis_summary,
            ),
        )

    @server.tool(
        name="get_swim_activity",
        title="Get a swim activity analysis",
        description=(
            "Return one owned normalized pool swim with bounded intervals, quality, "
            "comparison, and minimized feedback."
        ),
        annotations=READ_ONLY,
        structured_output=True,
    )
    async def get_swim_activity(
        activity_id: UUID,
        ctx: Context[Any, Any, Any],
        include_intervals: bool = True,
        include_lengths: bool = False,
        max_intervals: Annotated[int, Field(ge=1, le=100)] = 50,
    ) -> McpResult:
        if not 1 <= max_intervals <= 100:
            raise ToolError(
                _error(
                    "VALIDATION_FAILED",
                    "max_intervals must be between 1 and 100.",
                    _safe_request_id(ctx.request_id),
                )
            )
        args = {
            "activity_id": str(activity_id),
            "include_intervals": include_intervals,
            "include_lengths": include_lengths,
            "max_intervals": max_intervals,
        }
        return await execute(
            "get_swim_activity",
            ctx,
            frozenset({"activities:read", "analytics:read"}),
            args,
            lambda principal, request_id: read_service.get_swim_activity(
                principal,
                request_id,
                activity_id=EntityId(activity_id),
                include_intervals=include_intervals,
                include_lengths=include_lengths,
                max_intervals=max_intervals,
            ),
        )

    @server.tool(
        name="get_goal_progress",
        title="Get swimming goal progress",
        description=(
            "Return evidence-based progress toward an owned active goal and explicit "
            "sample quality."
        ),
        annotations=READ_ONLY,
        structured_output=True,
    )
    async def get_goal_progress(
        ctx: Context[Any, Any, Any], goal_id: UUID | None = None
    ) -> McpResult:
        args = {"goal_id": str(goal_id) if goal_id else None}
        return await execute(
            "get_goal_progress",
            ctx,
            frozenset({"goals:read", "analytics:read"}),
            args,
            lambda principal, request_id: read_service.get_goal_progress(
                principal, request_id, goal_id=EntityId(goal_id) if goal_id else None
            ),
        )

    @server.tool(
        name="get_sync_status",
        title="Get Garmin sync status",
        description=(
            "Return persisted Garmin connection health, recent runs, and staleness without "
            "starting a sync."
        ),
        annotations=READ_ONLY,
        structured_output=True,
    )
    async def get_sync_status(ctx: Context[Any, Any, Any]) -> McpResult:
        return await execute(
            "get_sync_status",
            ctx,
            frozenset({"sync:read"}),
            {},
            lambda principal, request_id: read_service.get_sync_status(principal, request_id),
        )

    if write_enabled and write_service is not None:
        _register_write_tools(server, write_service, execute_write)

    _harden_tool_schemas(server)
    return server


def _register_write_tools(
    server: FastMCP,
    write_service: McpWriteService,
    execute: Callable[
        [
            str,
            Context[Any, Any, Any],
            frozenset[str],
            dict[str, Any],
            Callable[[McpPrincipal, str, CorrelationId], Awaitable[McpResult]],
        ],
        Awaitable[McpResult],
    ],
) -> None:
    """Register P08 tools only when the independent write kill switch is enabled."""

    @server.tool(
        name="get_action_proposal",
        title="Get action proposal",
        description="Return exact persisted impact, hash, expiry, scope, and execution state.",
        annotations=READ_ONLY,
        structured_output=True,
    )
    async def get_action_proposal(proposal_id: UUID, ctx: Context[Any, Any, Any]) -> McpResult:
        args = {"proposal_id": str(proposal_id)}
        return await execute(
            "get_action_proposal",
            ctx,
            frozenset({"proposals:read"}),
            args,
            lambda principal, request_id, _: write_service.get_action_proposal(
                principal, request_id, EntityId(proposal_id)
            ),
        )

    @server.tool(
        name="get_job_status",
        title="Get background job status",
        description="Return status, retryability, safe references, and sanitized errors.",
        annotations=READ_ONLY,
        structured_output=True,
    )
    async def get_job_status(job_id: UUID, ctx: Context[Any, Any, Any]) -> McpResult:
        args = {"job_id": str(job_id)}
        return await execute(
            "get_job_status",
            ctx,
            frozenset({"operations:read"}),
            args,
            lambda principal, request_id, _: write_service.get_job_status(
                principal, request_id, EntityId(job_id)
            ),
        )

    @server.tool(
        name="sync_garmin_activities",
        title="Sync Garmin activities",
        description="Queue an idempotent Garmin read/import job; does not wait for the provider.",
        annotations=OPEN_WORLD_WRITE,
        structured_output=True,
    )
    async def sync_garmin_activities(
        idempotency_key: Annotated[str, Field(min_length=8, max_length=200)],
        ctx: Context[Any, Any, Any],
        from_date: LocalDate | None = None,
        force: bool = False,
    ) -> McpResult:
        args = {
            "from_date": from_date.isoformat() if from_date else None,
            "force": force,
            "idempotency_key": idempotency_key,
        }
        return await execute(
            "sync_garmin_activities",
            ctx,
            frozenset({"sync:run"}),
            args,
            lambda principal, request_id, _: write_service.sync_garmin_activities(
                principal,
                request_id,
                from_date=from_date,
                force=force,
                idempotency_key=idempotency_key,
            ),
        )

    @server.tool(
        name="record_session_feedback",
        title="Record post-swim feedback",
        description="Store bounded feedback for an owned activity; this is not medical diagnosis.",
        annotations=LOCAL_WRITE,
        structured_output=True,
    )
    async def record_session_feedback(
        activity_id: UUID,
        rpe: Annotated[int, Field(ge=1, le=10)],
        technique: Annotated[str, Field(min_length=1, max_length=40)],
        pain: dict[str, Any],
        idempotency_key: Annotated[str, Field(min_length=8, max_length=200)],
        ctx: Context[Any, Any, Any],
        notes: Annotated[str | None, Field(max_length=2000)] = None,
    ) -> McpResult:
        args = {
            "activity_id": str(activity_id),
            "rpe": rpe,
            "technique": technique,
            "pain": pain,
            "notes": notes,
            "idempotency_key": idempotency_key,
        }
        return await execute(
            "record_session_feedback",
            ctx,
            frozenset({"feedback:write"}),
            args,
            lambda principal, request_id, correlation_id: write_service.record_session_feedback(
                principal,
                request_id,
                activity_id=EntityId(activity_id),
                rpe=rpe,
                technique=technique,
                pain=pain,
                notes=notes,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
            ),
        )

    @server.tool(
        name="create_workout_draft",
        title="Create a validated workout draft",
        description="Create a local canonical draft; never publishes or schedules externally.",
        annotations=LOCAL_WRITE,
        structured_output=True,
    )
    async def create_workout_draft(
        definition: CanonicalWorkout,
        ctx: Context[Any, Any, Any],
        pool_id: UUID | None = None,
    ) -> McpResult:
        args = {
            "definition": definition.model_dump(mode="json"),
            "pool_id": str(pool_id) if pool_id else None,
        }
        return await execute(
            "create_workout_draft",
            ctx,
            frozenset({"workouts:write"}),
            args,
            lambda principal, request_id, correlation_id: write_service.create_workout_draft(
                principal,
                request_id,
                definition=definition,
                pool_id=EntityId(pool_id) if pool_id else None,
                correlation_id=correlation_id,
            ),
        )

    @server.tool(
        name="propose_workout_change",
        title="Propose a workout change",
        description="Persist an exact before/after proposal without applying the change.",
        annotations=LOCAL_WRITE,
        structured_output=True,
    )
    async def propose_workout_change(
        workout_id: UUID,
        expected_revision: Annotated[int, Field(ge=1)],
        change_request: dict[str, Any],
        ctx: Context[Any, Any, Any],
    ) -> McpResult:
        args = {
            "workout_id": str(workout_id),
            "expected_revision": expected_revision,
            "change_request": change_request,
        }
        return await execute(
            "propose_workout_change",
            ctx,
            frozenset({"workouts:write", "proposals:write"}),
            args,
            lambda principal, request_id, correlation_id: write_service.propose_workout_change(
                principal,
                request_id,
                workout_id=EntityId(workout_id),
                expected_revision=expected_revision,
                change_request=change_request,
                correlation_id=correlation_id,
            ),
        )

    @server.tool(
        name="propose_workout_reschedule",
        title="Propose rescheduling a workout",
        description="Persist a calendar-impact proposal without changing any schedule.",
        annotations=LOCAL_WRITE,
        structured_output=True,
    )
    async def propose_workout_reschedule(
        workout_id: UUID,
        new_date: LocalDate,
        ctx: Context[Any, Any, Any],
        local_time: time | None = None,
    ) -> McpResult:
        args = {
            "workout_id": str(workout_id),
            "new_date": new_date.isoformat(),
            "local_time": local_time.isoformat() if local_time else None,
        }
        return await execute(
            "propose_workout_reschedule",
            ctx,
            frozenset({"workouts:write", "proposals:write"}),
            args,
            lambda principal, request_id, correlation_id: write_service.propose_workout_reschedule(
                principal,
                request_id,
                workout_id=EntityId(workout_id),
                new_date=new_date,
                local_time=local_time,
                correlation_id=correlation_id,
            ),
        )

    @server.tool(
        name="preview_garmin_publish",
        title="Preview Garmin publication",
        description="Compile and persist a reviewable proposal; never calls Garmin.",
        annotations=LOCAL_WRITE,
        structured_output=True,
    )
    async def preview_garmin_publish(
        workout_id: UUID,
        revision: Annotated[int, Field(ge=1)],
        schedule_date: LocalDate,
        idempotency_key: Annotated[str, Field(min_length=8, max_length=200)],
        ctx: Context[Any, Any, Any],
        target_device_id: UUID | None = None,
    ) -> McpResult:
        args = {
            "workout_id": str(workout_id),
            "revision": revision,
            "schedule_date": schedule_date.isoformat(),
            "target_device_id": str(target_device_id) if target_device_id else None,
            "idempotency_key": idempotency_key,
        }
        return await execute(
            "preview_garmin_publish",
            ctx,
            frozenset({"garmin:publish", "proposals:write"}),
            args,
            lambda principal, request_id, correlation_id: write_service.preview_garmin_publish(
                principal,
                request_id,
                workout_id=EntityId(workout_id),
                revision=revision,
                schedule_date=schedule_date,
                target_device_id=(EntityId(target_device_id) if target_device_id else None),
                correlation_id=correlation_id,
            ),
        )

    @server.tool(
        name="cancel_action_proposal",
        title="Cancel an action proposal",
        description="Cancel a cancellable owned proposal while preserving audit history.",
        annotations=DESTRUCTIVE_LOCAL_WRITE,
        structured_output=True,
    )
    async def cancel_action_proposal(
        proposal_id: UUID,
        ctx: Context[Any, Any, Any],
        reason: Annotated[str | None, Field(max_length=500)] = None,
    ) -> McpResult:
        args = {"proposal_id": str(proposal_id), "reason": reason}
        return await execute(
            "cancel_action_proposal",
            ctx,
            frozenset({"proposals:write"}),
            args,
            lambda principal, request_id, correlation_id: write_service.cancel_action_proposal(
                principal,
                request_id,
                proposal_id=EntityId(proposal_id),
                reason=reason,
                correlation_id=correlation_id,
            ),
        )

    @server.tool(
        name="approve_action_proposal",
        title="Approve an exact action proposal",
        description="Record an explicit exact-hash decision; never executes the action.",
        annotations=LOCAL_WRITE,
        structured_output=True,
    )
    async def approve_action_proposal(
        proposal_id: UUID,
        expected_action_hash: Annotated[str, Field(min_length=64, max_length=64)],
        decision: Literal["APPROVE", "REJECT"],
        confirmation_text: Annotated[str, Field(min_length=1, max_length=1000)],
        ctx: Context[Any, Any, Any],
    ) -> McpResult:
        args = {
            "proposal_id": str(proposal_id),
            "expected_action_hash": expected_action_hash,
            "decision": decision,
            "confirmation_text": confirmation_text,
        }
        return await execute(
            "approve_action_proposal",
            ctx,
            frozenset({"proposals:approve"}),
            args,
            lambda principal, request_id, correlation_id: write_service.approve_action_proposal(
                principal,
                request_id,
                proposal_id=EntityId(proposal_id),
                expected_action_hash=expected_action_hash,
                decision=decision,
                confirmation_text=confirmation_text,
                correlation_id=correlation_id,
            ),
        )

    @server.tool(
        name="execute_approved_action",
        title="Execute an approved action",
        description="Queue a separately approved exact action with its dynamic action scope.",
        annotations=OPEN_WORLD_WRITE,
        structured_output=True,
    )
    async def execute_approved_action(
        proposal_id: UUID,
        idempotency_key: Annotated[str, Field(min_length=8, max_length=200)],
        ctx: Context[Any, Any, Any],
    ) -> McpResult:
        args = {"proposal_id": str(proposal_id), "idempotency_key": idempotency_key}
        return await execute(
            "execute_approved_action",
            ctx,
            frozenset({"proposals:approve"}),
            args,
            lambda principal, request_id, correlation_id: write_service.execute_approved_action(
                principal,
                request_id,
                proposal_id=EntityId(proposal_id),
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
            ),
        )

    @server.tool(
        name="retry_failed_job",
        title="Retry a safe failed job",
        description="Retry only a user-owned failure explicitly classified as safe and retryable.",
        annotations=OPEN_WORLD_WRITE,
        structured_output=True,
    )
    async def retry_failed_job(
        job_id: UUID,
        idempotency_key: Annotated[str, Field(min_length=8, max_length=200)],
        ctx: Context[Any, Any, Any],
    ) -> McpResult:
        args = {"job_id": str(job_id), "idempotency_key": idempotency_key}
        return await execute(
            "retry_failed_job",
            ctx,
            frozenset({"operations:retry"}),
            args,
            lambda principal, request_id, correlation_id: write_service.retry_failed_job(
                principal,
                request_id,
                job_id=EntityId(job_id),
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
            ),
        )


def _result_causation(result: McpResult) -> EntityId | None:
    for key in ("proposal_id", "job_id", "workout_id", "activity_id"):
        raw = result.data.get(key)
        if isinstance(raw, str):
            try:
                return EntityId.parse(raw)
            except ValueError:
                continue
    return None


def _argument_causation(arguments: dict[str, Any]) -> EntityId | None:
    for key in ("proposal_id", "job_id", "workout_id", "activity_id"):
        raw = arguments.get(key)
        if isinstance(raw, str):
            try:
                return EntityId.parse(raw)
            except ValueError:
                continue
    return None


def _register_p00_capabilities(server: FastMCP) -> None:
    @server.tool(
        name="get_capabilities",
        title="Get Swim Coach capabilities",
        description="Return the harmless capability check while OAuth is not configured.",
        annotations=READ_ONLY,
        structured_output=True,
    )
    def get_capabilities() -> CapabilityResult:
        return p00_capabilities()


def _harden_tool_schemas(server: FastMCP) -> None:
    """Keep FastMCP's generated function schemas closed to unknown arguments."""

    for tool in server._tool_manager._tools.values():
        tool.parameters["additionalProperties"] = False
        tool.fn_metadata.arg_model.model_config["extra"] = "forbid"
        tool.fn_metadata.arg_model.model_rebuild(force=True)


def _error(
    code: str,
    message: str,
    request_id: str,
    details: dict[str, str | int | bool] | None = None,
) -> str:
    return json.dumps(
        {
            "schema_version": "1.0",
            "request_id": request_id,
            "status": "NEEDS_AUTHORIZATION"
            if code in {"AUTH_REQUIRED", "SCOPE_REQUIRED"}
            else "FAILED",
            "error": {
                "code": code,
                "message": message,
                "correlation_id": request_id,
                "retryable": False,
                "details": details or {},
            },
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _safe_request_id(value: str) -> str:
    if len(value) <= 100 and all(character.isalnum() or character in "-_.:" for character in value):
        return value
    return f"req_{hashlib.sha256(value.encode()).hexdigest()}"
