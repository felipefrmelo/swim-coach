"""Authenticated, read-only P05 MCP server."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from datetime import date as LocalDate
from datetime import datetime, time
from time import perf_counter
from typing import Annotated, Any, Literal, cast
from urllib.parse import urlsplit
from uuid import UUID

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.fastmcp.server import Settings as FastMCPSettings
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from mcp.types import Tool as McpTool
from pydantic import AnyHttpUrl, Field

from swim_coach.application.queries.get_capabilities import (
    CapabilityResult,
)
from swim_coach.application.queries.get_capabilities import (
    get_capabilities as p00_capabilities,
)
from swim_coach.application.services.coach_commands import CoachCommandService
from swim_coach.application.services.mcp_read import (
    MCP_READ_TOOL_SCOPES,
    McpPrincipal,
    McpReadService,
    McpResult,
    McpResultV2,
    McpWarning,
)
from swim_coach.application.services.mcp_write import (
    MCP_PLANNING_TOOL_SCOPES,
    MCP_PLANNING_TOOLS,
    MCP_WRITE_TOOL_SCOPES,
    McpWriteService,
)
from swim_coach.domain.planning import PlanningPreferences
from swim_coach.domain.shared.errors import DomainError
from swim_coach.domain.shared.value_objects import CorrelationId, EntityId
from swim_coach.domain.workouts import CanonicalWorkout
from swim_coach.interfaces.mcp.ui import (
    MCP_UI_RESOURCE_URIS,
    MCP_UI_TOOL_SCOPES,
    MCP_UI_TOOLS,
    activity_card,
    goal_card,
    proposal_card,
    register_ui_resources,
    sync_card,
    ui_tool_meta,
    workout_card,
)

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
DESTRUCTIVE_OPEN_WORLD_WRITE = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=True,
    openWorldHint=True,
)

_GARMIN_WARNING_MESSAGES = {
    "DRILL_STROKE_DOWNGRADED_TO_CHOICE": (
        "Garmin will receive this drill stroke as the generic choice stroke."
    ),
    "EQUIPMENT_OMITTED_FROM_GARMIN_PAYLOAD": (
        "Garmin will not receive the equipment configured for this workout step."
    ),
    "PACE_TARGET_DOWNGRADED_TO_TEXT": (
        "The desired pace is included as step text because a native Garmin pace target "
        "is unavailable."
    ),
    "RPE_TARGET_DOWNGRADED_TO_TEXT": (
        "The RPE target is included as step text because a native Garmin effort target "
        "is unavailable."
    ),
    "RPE_TARGET_MAPPED_TO_GARMIN_EFFORT_CATEGORY": (
        "The RPE range was mapped to a Garmin effort category and preserved in the step text."
    ),
    "ZONE_TARGET_DOWNGRADED_TO_TEXT": (
        "The training zone is included as step text because a native Garmin zone target "
        "is unavailable."
    ),
}

_McpSchemaVersion = Literal["1.0", "2.0"]


def _garmin_warning(code: str) -> McpWarning:
    return McpWarning(
        code=code,
        message=_GARMIN_WARNING_MESSAGES.get(code, "Garmin adjusted part of the workout payload."),
    )


class SwimCoachFastMCP(FastMCP):
    """Expose standard securitySchemes and its ChatGPT compatibility mirror."""

    async def list_tools(self) -> list[McpTool]:
        tools = await super().list_tools()
        advertised: list[McpTool] = []
        for tool in tools:
            security_schemes = (tool.meta or {}).get("securitySchemes")
            payload = tool.model_dump(mode="json", by_alias=True, exclude_none=True)
            if security_schemes is not None:
                payload["securitySchemes"] = security_schemes
            advertised.append(McpTool.model_validate(payload))
        return advertised


def create_mcp_server(
    *,
    read_service: McpReadService | None = None,
    write_service: McpWriteService | None = None,
    coach_service: CoachCommandService | None = None,
    token_verifier: TokenVerifier | None = None,
    oauth_issuer: str | None = None,
    oauth_resource: str | None = None,
    ui_enabled: bool = False,
    v2_enabled: bool = False,
    pwa_base_url: str = "http://127.0.0.1:14173",
    allowed_hosts: list[str] | None = None,
    allowed_origins: list[str] | None = None,
) -> FastMCP:
    """Create a fail-closed read server; private tools exist only with OAuth configured."""

    FastMCPSettings.model_rebuild(_types_namespace={"FastMCP": FastMCP})
    envelope_schema_version: _McpSchemaVersion = "2.0" if v2_enabled else "1.0"
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
    ui_enabled = bool(oauth_enabled and write_enabled and ui_enabled)
    instructions = (
        "Swim Coach is a personal, ChatGPT-first swimming coach. Use the nine "
        "intent-level tools directly. Local saves need no extra confirmation. Calling "
        "publish_workout means the user asked to send that workout to Garmin; do not add "
        "proposal, hash, approval, execution, revision, or idempotency ceremony. Calling "
        "delete_workout means the user asked to remove the planned workout locally, from "
        "the calendar, and from Garmin after the host's destructive-action confirmation."
        if v2_enabled and oauth_enabled
        else "Swim Coach exposes authenticated, user-scoped swimming training data. "
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
    server = SwimCoachFastMCP(
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

    if ui_enabled:
        register_ui_resources(server, pwa_base_url=pwa_base_url)

    if not oauth_enabled:
        _register_p00_capabilities(server)
        _harden_tool_schemas(server)
        return server
    if read_service is None:  # Defensive; oauth_enabled already guarantees this.
        raise RuntimeError("MCP read service is missing")
    configured_oauth_resource = cast(str, oauth_resource)

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
            return cast(
                McpResult,
                _authorization_error_result(
                    code="AUTH_REQUIRED",
                    message="OAuth authentication is required.",
                    request_id=request_id,
                    oauth_resource=configured_oauth_resource,
                    schema_version=envelope_schema_version,
                ),
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
            return _result_with_schema_version(result, envelope_schema_version)
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
            if error.code in {"AUTH_REQUIRED", "SCOPE_REQUIRED"}:
                return cast(
                    McpResult,
                    _authorization_error_result(
                        code=error.code,
                        message=error.message,
                        request_id=request_id,
                        oauth_resource=configured_oauth_resource,
                        details=error.details,
                        schema_version=envelope_schema_version,
                    ),
                )
            raise ToolError(
                _error(
                    error.code,
                    error.message,
                    request_id,
                    error.details,
                    schema_version=envelope_schema_version,
                )
            ) from error

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
                    schema_version=envelope_schema_version,
                )
            )
        request_id = _safe_request_id(ctx.request_id)
        access_token = get_access_token()
        if access_token is None or not access_token.subject:
            return cast(
                McpResult,
                _authorization_error_result(
                    code="AUTH_REQUIRED",
                    message="OAuth authentication is required.",
                    request_id=request_id,
                    oauth_resource=configured_oauth_resource,
                    schema_version=envelope_schema_version,
                ),
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
            return _result_with_schema_version(result, envelope_schema_version)
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
            if error.code in {"AUTH_REQUIRED", "SCOPE_REQUIRED"}:
                return cast(
                    McpResult,
                    _authorization_error_result(
                        code=error.code,
                        message=error.message,
                        request_id=request_id,
                        oauth_resource=configured_oauth_resource,
                        details=error.details,
                        schema_version=envelope_schema_version,
                    ),
                )
            raise ToolError(
                _error(
                    error.code,
                    error.message,
                    request_id,
                    error.details,
                    schema_version=envelope_schema_version,
                )
            ) from error

    if v2_enabled:
        if write_service is None or coach_service is None:
            raise RuntimeError("MCP v2 requires coach and write services")
        _register_v2_tools(
            server,
            read_service=read_service,
            write_service=write_service,
            coach_service=coach_service,
            execute=execute,
            execute_write=execute_write,
        )
        _apply_v2_tool_security_schemes(server)
        _harden_tool_schemas(server)
        return server

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
            if ui_enabled:
                result.data["server_version"] = "0.3.0-optional-ui"
                result.data["phase"] = "P09"
                result.data["release_mode"] = "controlled-write-optional-ui"
                result.data["available_tools"] = [
                    *result.data["available_tools"],
                    *MCP_UI_TOOLS,
                ]
                result.data["custom_ui_enabled"] = True
                result.data["ui_resources"] = list(MCP_UI_RESOURCE_URIS.values())
                result.human_summary = (
                    "Swim Coach exposes authenticated reads, controlled writes, and optional "
                    "portable MCP Apps cards. Every workflow remains complete without UI."
                )
            if write_service is not None and getattr(write_service, "planning_enabled", False):
                result.data["server_version"] = "0.4.0-adaptive-planning"
                result.data["phase"] = "P10"
                result.data["release_mode"] = "controlled-write-optional-ui-planning"
                result.data["available_tools"] = [
                    *result.data["available_tools"],
                    *MCP_PLANNING_TOOLS,
                ]
                result.data["required_scopes"] = [
                    *result.data["required_scopes"],
                    "planning:write",
                ]
                result.data["adaptive_planning_enabled"] = True
                result.human_summary = (
                    "Swim Coach adds reproducible, explainable weekly plan proposals. "
                    "Planning never approves, applies, schedules, or publishes automatically."
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
                    schema_version=envelope_schema_version,
                )
            )
        if before is not None and before.tzinfo is None:
            raise ToolError(
                _error(
                    "VALIDATION_FAILED",
                    "before must include a timezone.",
                    _safe_request_id(ctx.request_id),
                    schema_version=envelope_schema_version,
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
            lambda principal, request_id: read_service.list_recent_swims_v1(
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
                    schema_version=envelope_schema_version,
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
            lambda principal, request_id: read_service.get_swim_activity_v1(
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
            lambda principal, request_id: read_service.get_goal_progress_v1(
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
    if ui_enabled and write_service is not None:
        _register_ui_tools(
            server,
            read_service,
            write_service,
            execute,
            pwa_base_url=pwa_base_url,
            schema_version=envelope_schema_version,
        )

    _apply_tool_security_schemes(server)
    _harden_tool_schemas(server)
    if not v2_enabled:
        _freeze_v1_tool_output_schemas(server)
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

    if getattr(write_service, "planning_enabled", False):

        @server.tool(
            name="propose_week_plan",
            title="Propose a weekly swim plan",
            description=(
                "Generate and persist a reproducible weekly plan proposal from owned context "
                "and versioned conservative rules; never approves, applies, or publishes it."
            ),
            annotations=LOCAL_WRITE,
            structured_output=True,
        )
        async def propose_week_plan(
            week_start: LocalDate,
            ctx: Context[Any, Any, Any],
            constraints: PlanningPreferences | None = None,
            user_notes: Annotated[str | None, Field(max_length=1000)] = None,
        ) -> McpResult:
            structured_constraints = (
                constraints.model_dump(mode="json", exclude_none=True) if constraints else {}
            )
            args = {
                "week_start": week_start.isoformat(),
                "constraints": structured_constraints,
                "user_notes": user_notes,
            }
            return await execute(
                "propose_week_plan",
                ctx,
                frozenset({"planning:write", "proposals:write"}),
                args,
                lambda principal, request_id, correlation_id: write_service.propose_week_plan(
                    principal,
                    request_id,
                    week_start=week_start,
                    constraints=structured_constraints,
                    user_notes=user_notes,
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
        title="Propose scheduling or rescheduling a workout",
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
        description=(
            "Apply an approved local action or queue an approved Garmin action with its "
            "dynamic action scope."
        ),
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


def _register_ui_tools(
    server: FastMCP,
    read_service: McpReadService,
    write_service: McpWriteService,
    execute: Callable[
        [
            str,
            Context[Any, Any, Any],
            frozenset[str],
            dict[str, Any],
            Callable[[McpPrincipal, str], Awaitable[McpResult]],
        ],
        Awaitable[McpResult],
    ],
    *,
    pwa_base_url: str,
    schema_version: _McpSchemaVersion,
) -> None:
    """Register presentation-only P09 tools after the headless data/action surface."""

    @server.tool(
        name="render_workout_card",
        title="Render workout or week card",
        description=(
            "Render an optional portable card from authoritative workout data. The underlying "
            "get_today_workout and get_week_plan tools remain complete without UI."
        ),
        annotations=READ_ONLY,
        meta=ui_tool_meta("workout"),
        structured_output=True,
    )
    async def render_workout_card(
        ctx: Context[Any, Any, Any],
        view: Literal["today", "week"] = "today",
        date: LocalDate | None = None,
        week_start: LocalDate | None = None,
    ) -> McpResult:
        if view == "today" and week_start is not None:
            raise ToolError(
                _error(
                    "VALIDATION_FAILED",
                    "week_start is only valid for the week view.",
                    _safe_request_id(ctx.request_id),
                    schema_version=schema_version,
                )
            )
        if view == "week" and date is not None:
            raise ToolError(
                _error(
                    "VALIDATION_FAILED",
                    "date is only valid for the today view.",
                    _safe_request_id(ctx.request_id),
                    schema_version=schema_version,
                )
            )
        args = {
            "view": view,
            "date": date.isoformat() if date else None,
            "week_start": week_start.isoformat() if week_start else None,
        }

        async def query(principal: McpPrincipal, request_id: str) -> McpResult:
            result = (
                await read_service.get_week_plan(
                    principal,
                    request_id,
                    week_start=week_start,
                )
                if view == "week"
                else await read_service.get_today_workout(
                    principal,
                    request_id,
                    target_date=date,
                    include_steps=True,
                    include_publish_status=True,
                )
            )
            return workout_card(result, pwa_base_url=pwa_base_url, view=view)

        return await execute(
            "render_workout_card",
            ctx,
            frozenset({"workouts:read"}),
            args,
            query,
        )

    @server.tool(
        name="render_activity_comparison_card",
        title="Render swim comparison card",
        description=(
            "Render an optional planned-versus-executed swim card with bounded intervals and "
            "feedback status; raw FIT is never returned."
        ),
        annotations=READ_ONLY,
        meta=ui_tool_meta("activity"),
        structured_output=True,
    )
    async def render_activity_comparison_card(
        activity_id: UUID,
        ctx: Context[Any, Any, Any],
        max_intervals: Annotated[int, Field(ge=1, le=30)] = 20,
    ) -> McpResult:
        args = {"activity_id": str(activity_id), "max_intervals": max_intervals}

        async def query(principal: McpPrincipal, request_id: str) -> McpResult:
            result = await read_service.get_swim_activity_v1(
                principal,
                request_id,
                activity_id=EntityId(activity_id),
                include_intervals=True,
                include_lengths=False,
                max_intervals=max_intervals,
            )
            return activity_card(result, pwa_base_url=pwa_base_url)

        return await execute(
            "render_activity_comparison_card",
            ctx,
            frozenset({"activities:read", "analytics:read"}),
            args,
            query,
        )

    @server.tool(
        name="render_goal_progress_card",
        title="Render goal progress card",
        description="Render an optional evidence-based goal card with sample quality.",
        annotations=READ_ONLY,
        meta=ui_tool_meta("goal"),
        structured_output=True,
    )
    async def render_goal_progress_card(
        ctx: Context[Any, Any, Any], goal_id: UUID | None = None
    ) -> McpResult:
        args = {"goal_id": str(goal_id) if goal_id else None}

        async def query(principal: McpPrincipal, request_id: str) -> McpResult:
            result = await read_service.get_goal_progress_v1(
                principal,
                request_id,
                goal_id=EntityId(goal_id) if goal_id else None,
            )
            return goal_card(result, pwa_base_url=pwa_base_url)

        return await execute(
            "render_goal_progress_card",
            ctx,
            frozenset({"goals:read", "analytics:read"}),
            args,
            query,
        )

    @server.tool(
        name="render_proposal_confirmation_card",
        title="Render exact proposal confirmation card",
        description=(
            "Render an owned persisted proposal. The card may approve or reject the exact hash, "
            "but never executes the approved action."
        ),
        annotations=READ_ONLY,
        meta=ui_tool_meta("proposal"),
        structured_output=True,
    )
    async def render_proposal_confirmation_card(
        proposal_id: UUID,
        ctx: Context[Any, Any, Any],
    ) -> McpResult:
        args = {"proposal_id": str(proposal_id)}

        async def query(principal: McpPrincipal, request_id: str) -> McpResult:
            result = await write_service.get_action_proposal(
                principal,
                request_id,
                EntityId(proposal_id),
            )
            return proposal_card(result)

        return await execute(
            "render_proposal_confirmation_card",
            ctx,
            frozenset({"proposals:read"}),
            args,
            query,
        )

    @server.tool(
        name="render_sync_status_card",
        title="Render sync and job status card",
        description=(
            "Render persisted Garmin sync state and, when requested, one owned job with a safe "
            "retry action only when the server classifies it retryable."
        ),
        annotations=READ_ONLY,
        meta=ui_tool_meta("sync"),
        structured_output=True,
    )
    async def render_sync_status_card(
        ctx: Context[Any, Any, Any], job_id: UUID | None = None
    ) -> McpResult:
        args = {"job_id": str(job_id) if job_id else None}
        scopes = {"sync:read"}
        if job_id is not None:
            scopes.add("operations:read")

        async def query(principal: McpPrincipal, request_id: str) -> McpResult:
            result = await read_service.get_sync_status(principal, request_id)
            job = (
                await write_service.get_job_status(principal, request_id, EntityId(job_id))
                if job_id
                else None
            )
            return sync_card(result, job=job)

        return await execute(
            "render_sync_status_card",
            ctx,
            frozenset(scopes),
            args,
            query,
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


def _register_v2_tools(
    server: SwimCoachFastMCP,
    *,
    read_service: McpReadService,
    write_service: McpWriteService,
    coach_service: CoachCommandService,
    execute: Callable[..., Awaitable[McpResult]],
    execute_write: Callable[..., Awaitable[McpResult]],
) -> None:
    """Register the complete public v2 surface: nine intent-level tools."""

    scope = frozenset({"coach"})

    @server.tool(
        name="get_coach_context",
        title="Get swim coach context",
        description=(
            "Return profile, goal, pool, availability, Garmin health, progress, and summary."
        ),
        annotations=READ_ONLY,
        structured_output=True,
    )
    async def get_coach_context(
        ctx: Context[Any, Any, Any], include_constraints: bool = True
    ) -> McpResultV2:
        args = {"include_constraints": include_constraints}

        async def query(principal: McpPrincipal, request_id: str) -> McpResult:
            training = await read_service.get_training_context(
                principal, request_id, include_constraints=include_constraints
            )
            sync = await read_service.get_sync_status(principal, request_id)
            try:
                progress = await read_service.get_goal_progress(principal, request_id, goal_id=None)
                progress_data: dict[str, Any] | None = progress.data
            except DomainError as error:
                if error.code != "RESOURCE_NOT_FOUND":
                    raise
                progress_data = None
            return McpResult(
                request_id=request_id,
                status="OK",
                data={
                    "training": training.data,
                    "goal_progress": progress_data,
                    "garmin": sync.data,
                    "capabilities": {
                        "save_workout": True,
                        "generate_week": coach_service.planning_enabled,
                        "publish_workout": coach_service.garmin_write_enabled,
                        "delete_workout": True,
                    },
                },
                warnings=[*training.warnings, *sync.warnings],
                human_summary=(
                    f"{training.human_summary} Garmin is "
                    f"{sync.data.get('connection_status', 'unknown')}."
                ),
            )

        return _as_v2_result(await execute("get_coach_context", ctx, scope, args, query))

    @server.tool(
        name="get_workouts",
        title="Get swim workouts",
        description="Return one workout or workouts for a date or week with schedule and steps.",
        annotations=READ_ONLY,
        structured_output=True,
    )
    async def get_workouts(
        ctx: Context[Any, Any, Any],
        workout_id: UUID | None = None,
        date: LocalDate | None = None,
        week_start: LocalDate | None = None,
        include_steps: bool = True,
    ) -> McpResultV2:
        args = {
            "workout_id": str(workout_id) if workout_id else None,
            "date": date.isoformat() if date else None,
            "week_start": week_start.isoformat() if week_start else None,
            "include_steps": include_steps,
        }
        return _as_v2_result(
            await execute(
                "get_workouts",
                ctx,
                scope,
                args,
                lambda principal, request_id: read_service.get_workouts(
                    principal,
                    request_id,
                    workout_id=EntityId(workout_id) if workout_id else None,
                    target_date=date,
                    week_start=week_start,
                    include_steps=include_steps,
                ),
            )
        )

    @server.tool(
        name="get_swims",
        title="Get pool swims",
        description="Return one analyzed pool swim or a concise recent list.",
        annotations=READ_ONLY,
        structured_output=True,
    )
    async def get_swims(
        ctx: Context[Any, Any, Any],
        activity_id: UUID | None = None,
        limit: Annotated[int, Field(ge=1, le=20)] = 5,
        include_intervals: bool = True,
    ) -> McpResultV2:
        args = {
            "activity_id": str(activity_id) if activity_id else None,
            "limit": limit,
            "include_intervals": include_intervals,
        }

        async def query(principal: McpPrincipal, request_id: str) -> McpResult:
            if activity_id is not None:
                return await read_service.get_swim_activity(
                    principal,
                    request_id,
                    activity_id=EntityId(activity_id),
                    include_intervals=include_intervals,
                    include_lengths=False,
                    max_intervals=50,
                )
            return await read_service.list_recent_swims(
                principal,
                request_id,
                limit=limit,
                before=None,
                include_analysis_summary=True,
            )

        return _as_v2_result(await execute("get_swims", ctx, scope, args, query))

    @server.tool(
        name="save_workout",
        title="Save and schedule a swim workout",
        description=(
            "Create or edit a canonical pool workout and optionally schedule it locally in "
            "one call. Revisions and concurrency are managed by the server."
        ),
        annotations=LOCAL_WRITE,
        structured_output=True,
    )
    async def save_workout(
        ctx: Context[Any, Any, Any],
        definition: CanonicalWorkout,
        workout_id: UUID | None = None,
        pool_id: UUID | None = None,
        scheduled_date: LocalDate | None = None,
        scheduled_start_time: time | None = None,
        change_reason: Annotated[str | None, Field(max_length=500)] = None,
    ) -> McpResultV2:
        args = {
            "workout_id": str(workout_id) if workout_id else None,
            "pool_id": str(pool_id) if pool_id else None,
            "scheduled_date": scheduled_date.isoformat() if scheduled_date else None,
            "scheduled_start_time": scheduled_start_time.isoformat()
            if scheduled_start_time
            else None,
            "definition": definition.model_dump(mode="json"),
            "change_reason": change_reason,
        }

        async def command(
            principal: McpPrincipal, request_id: str, correlation_id: CorrelationId
        ) -> McpResult:
            detail = await coach_service.save_workout(
                principal.user_id,
                definition,
                workout_id=EntityId(workout_id) if workout_id else None,
                pool_id=EntityId(pool_id) if pool_id else None,
                scheduled_date=scheduled_date,
                scheduled_start_time=scheduled_start_time,
                change_reason=change_reason,
                correlation_id=correlation_id,
            )
            revision = detail.current_revision
            return McpResult(
                request_id=request_id,
                status="OK",
                data={
                    "workout_id": str(detail.workout.id),
                    "title": detail.workout.title,
                    "status": detail.workout.status.value,
                    "revision": revision.revision_number,
                    "distance_m": revision.totals.distance_m,
                    "scheduled_date": detail.schedule.scheduled_date.isoformat()
                    if detail.schedule
                    else None,
                    "scheduled_start_time": detail.schedule.scheduled_start_time.isoformat(
                        timespec="minutes"
                    )
                    if detail.schedule and detail.schedule.scheduled_start_time
                    else None,
                },
                human_summary=f"Saved {detail.workout.title} locally.",
            )

        return _as_v2_result(await execute_write("save_workout", ctx, scope, args, command))

    @server.tool(
        name="publish_workout",
        title="Publish a swim workout to Garmin",
        description=(
            "Create or update the Garmin workout and calendar date idempotently. "
            "Use when the user asks to send or publish a workout."
        ),
        annotations=OPEN_WORLD_WRITE,
        structured_output=True,
    )
    async def publish_workout(
        ctx: Context[Any, Any, Any],
        workout_id: UUID,
        scheduled_date: LocalDate | None = None,
        scheduled_start_time: time | None = None,
        target_device_id: UUID | None = None,
    ) -> McpResultV2:
        args = {
            "workout_id": str(workout_id),
            "scheduled_date": scheduled_date.isoformat() if scheduled_date else None,
            "scheduled_start_time": scheduled_start_time.isoformat()
            if scheduled_start_time
            else None,
            "target_device_id": str(target_device_id) if target_device_id else None,
        }

        async def command(
            principal: McpPrincipal, request_id: str, correlation_id: CorrelationId
        ) -> McpResult:
            result = await coach_service.publish_workout(
                principal.user_id,
                EntityId(workout_id),
                scheduled_date=scheduled_date,
                scheduled_start_time=scheduled_start_time,
                device_id=EntityId(target_device_id) if target_device_id else None,
                correlation_id=correlation_id,
            )
            return McpResult(
                request_id=request_id,
                status="OK",
                data={
                    "workout_id": str(result.workout_id),
                    "revision": result.revision,
                    "scheduled_date": result.scheduled_date,
                    "status": result.status,
                    "job_id": str(result.job_id) if result.job_id else None,
                    "replayed": result.replayed,
                },
                warnings=[_garmin_warning(code) for code in result.warnings],
                human_summary=(
                    "Garmin publication is queued."
                    if result.job_id
                    else "This workout is already current on Garmin."
                ),
            )

        return _as_v2_result(await execute_write("publish_workout", ctx, scope, args, command))

    @server.tool(
        name="delete_workout",
        title="Delete a swim workout everywhere",
        description=(
            "Remove a planned workout from Swim Coach, its local calendar, and Garmin. "
            "Completed or activity-matched workouts are protected."
        ),
        annotations=DESTRUCTIVE_OPEN_WORLD_WRITE,
        structured_output=True,
    )
    async def delete_workout(
        workout_id: UUID,
        ctx: Context[Any, Any, Any],
    ) -> McpResultV2:
        args = {"workout_id": str(workout_id)}

        async def command(
            principal: McpPrincipal, request_id: str, correlation_id: CorrelationId
        ) -> McpResult:
            result = await coach_service.delete_workout(
                principal.user_id,
                EntityId(workout_id),
                correlation_id=correlation_id,
            )
            return McpResult(
                request_id=request_id,
                status="ACCEPTED",
                data={
                    "workout_id": str(result.workout_id),
                    "local_removed": result.local_removed,
                    "calendar_removed": result.calendar_removed,
                    "garmin_cleanup": result.garmin_cleanup,
                    "job_id": str(result.job_id),
                    "replayed": result.replayed,
                },
                human_summary=(
                    "The workout was removed locally; Garmin cleanup is running."
                    if result.garmin_cleanup == "QUEUED"
                    else "The workout has already been deleted everywhere."
                ),
            )

        return _as_v2_result(await execute_write("delete_workout", ctx, scope, args, command))

    @server.tool(
        name="generate_week",
        title="Generate and save a swim week",
        description="Generate a deterministic week and save its sessions to the local calendar.",
        annotations=LOCAL_WRITE,
        structured_output=True,
    )
    async def generate_week(
        ctx: Context[Any, Any, Any],
        week_start: LocalDate,
        session_count: Annotated[int | None, Field(ge=1, le=7)] = None,
        max_session_duration_minutes: Annotated[int | None, Field(ge=20, le=120)] = None,
        focus: Literal["BALANCED", "TECHNIQUE", "ENDURANCE", "GOAL_PACE"] = "BALANCED",
        avoid_high_intensity: bool = False,
    ) -> McpResultV2:
        args = {
            "week_start": week_start.isoformat(),
            "session_count": session_count,
            "max_session_duration_minutes": max_session_duration_minutes,
            "focus": focus,
            "avoid_high_intensity": avoid_high_intensity,
        }

        async def command(
            principal: McpPrincipal, request_id: str, correlation_id: CorrelationId
        ) -> McpResult:
            result = await coach_service.generate_week(
                principal.user_id,
                actor_id=principal.subject,
                week_start=week_start,
                preferences=PlanningPreferences(
                    session_count=session_count,
                    max_session_duration_minutes=max_session_duration_minutes,
                    focus=focus,
                    avoid_high_intensity=avoid_high_intensity,
                ),
                correlation_id=correlation_id,
            )
            sessions = result.week.get("sessions", [])
            return McpResult(
                request_id=request_id,
                status="OK",
                data={
                    "planning_run_id": str(result.planning_run_id),
                    "workout_ids": [str(item) for item in result.workout_ids],
                    "week_start": week_start.isoformat(),
                    "session_count": len(result.workout_ids),
                    "target_volume_m": result.week.get("target_volume_m"),
                    "sessions": sessions,
                    "warnings": result.week.get("warnings", []),
                    "replayed": result.replayed,
                },
                human_summary=f"Saved {len(result.workout_ids)} workouts for the week.",
            )

        return _as_v2_result(await execute_write("generate_week", ctx, scope, args, command))

    @server.tool(
        name="sync_garmin",
        title="Sync Garmin activities",
        description="Queue an idempotent Garmin activity sync and return the job state.",
        annotations=OPEN_WORLD_WRITE,
        structured_output=True,
    )
    async def sync_garmin(
        ctx: Context[Any, Any, Any],
        from_date: LocalDate | None = None,
        force: bool = False,
    ) -> McpResultV2:
        args = {"from_date": from_date.isoformat() if from_date else None, "force": force}

        async def command(
            principal: McpPrincipal, request_id: str, correlation_id: CorrelationId
        ) -> McpResult:
            del correlation_id
            bucket = datetime.now().strftime("%Y%m%d%H")
            return await write_service.sync_garmin_activities(
                principal,
                request_id,
                from_date=from_date,
                force=force,
                idempotency_key=f"coach-sync:{bucket}:{from_date}:{force}",
            )

        return _as_v2_result(await execute_write("sync_garmin", ctx, scope, args, command))

    @server.tool(
        name="save_feedback",
        title="Save post-swim feedback",
        description="Store effort, technique, pain signal, and notes for a pool swim.",
        annotations=LOCAL_WRITE,
        structured_output=True,
    )
    async def save_feedback(
        ctx: Context[Any, Any, Any],
        activity_id: UUID,
        rpe: Annotated[int | None, Field(ge=1, le=10)] = None,
        technique: str | None = None,
        feeling_score: Annotated[int | None, Field(ge=0, le=100)] = None,
        pain_present: bool = False,
        pain_location: Annotated[str | None, Field(max_length=120)] = None,
        pain_intensity: Annotated[int | None, Field(ge=1, le=10)] = None,
        notes: Annotated[str | None, Field(max_length=2000)] = None,
    ) -> McpResultV2:
        args = {
            "activity_id": str(activity_id),
            "rpe": rpe,
            "technique": technique,
            "feeling_score": feeling_score,
            "pain_present": pain_present,
            "pain_location": pain_location,
            "pain_intensity": pain_intensity,
            "notes": notes,
        }

        async def command(
            principal: McpPrincipal, request_id: str, correlation_id: CorrelationId
        ) -> McpResult:
            digest = hashlib.sha256(
                json.dumps(args, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            return await write_service.record_session_feedback(
                principal,
                request_id,
                activity_id=EntityId(activity_id),
                rpe=rpe,
                technique=technique,
                feeling_score=feeling_score,
                pain={
                    "present": pain_present,
                    "location": pain_location,
                    "intensity": pain_intensity,
                },
                notes=notes,
                idempotency_key=f"coach-feedback:{digest}",
                correlation_id=correlation_id,
                reuse_idempotency_key_when_state_changed=True,
                preserve_existing_feeling_score=False,
            )

        return _as_v2_result(await execute_write("save_feedback", ctx, scope, args, command))


def _apply_v2_tool_security_schemes(server: SwimCoachFastMCP) -> None:
    for tool in server._tool_manager._tools.values():
        tool.meta = {
            **(tool.meta or {}),
            "securitySchemes": [{"type": "oauth2", "scopes": ["coach"]}],
        }


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


def _apply_tool_security_schemes(server: SwimCoachFastMCP) -> None:
    """Advertise exact per-tool OAuth scopes on the standard and compatibility surfaces."""

    scope_catalog = {
        **MCP_READ_TOOL_SCOPES,
        **MCP_WRITE_TOOL_SCOPES,
        **MCP_PLANNING_TOOL_SCOPES,
        **MCP_UI_TOOL_SCOPES,
    }
    for name, tool in server._tool_manager._tools.items():
        try:
            scopes = scope_catalog[name]
        except KeyError as error:  # pragma: no cover - startup invariant
            raise RuntimeError(f"OAuth scope metadata is missing for MCP tool {name!r}") from error
        security_schemes = [{"type": "oauth2", "scopes": list(scopes)}]
        tool.meta = {
            **(tool.meta or {}),
            "securitySchemes": security_schemes,
        }


def _harden_tool_schemas(server: FastMCP) -> None:
    """Keep FastMCP's generated function schemas closed to unknown arguments."""

    for tool in server._tool_manager._tools.values():
        tool.parameters["additionalProperties"] = False
        tool.fn_metadata.arg_model.model_config["extra"] = "forbid"
        tool.fn_metadata.arg_model.model_rebuild(force=True)


def _freeze_v1_tool_output_schemas(server: FastMCP) -> None:
    """Advertise the legacy server's already-enforced runtime envelope as exactly v1."""

    for tool in server._tool_manager._tools.values():
        for schema in (tool.output_schema, tool.fn_metadata.output_schema):
            if schema is None:
                continue
            properties = schema.get("properties")
            if not isinstance(properties, dict):
                continue
            properties["schema_version"] = {
                "const": "1.0",
                "default": "1.0",
                "title": "Schema Version",
                "type": "string",
            }


def _authorization_error_result(
    *,
    code: str,
    message: str,
    request_id: str,
    oauth_resource: str,
    details: dict[str, str | int | bool] | None = None,
    schema_version: _McpSchemaVersion,
) -> CallToolResult:
    """Return an MCP OAuth challenge while preserving a model-readable error envelope."""

    safe_details = details or {}
    raw_scope = safe_details.get("scope")
    required_scopes = raw_scope.split() if isinstance(raw_scope, str) else []
    structured = McpResult(
        schema_version=schema_version,
        request_id=request_id,
        status="PARTIAL",
        data={
            "authorization": {
                "status": "NEEDS_AUTHORIZATION",
                "code": code,
                "required_scopes": required_scopes,
            }
        },
        human_summary=message,
    )
    return CallToolResult(
        content=[
            TextContent(
                type="text",
                text=_error(
                    code,
                    message,
                    request_id,
                    safe_details,
                    schema_version=schema_version,
                ),
            )
        ],
        structuredContent=structured.model_dump(mode="json"),
        isError=True,
        _meta={
            "mcp/www_authenticate": [
                _authorization_challenge(
                    code=code,
                    message=message,
                    oauth_resource=oauth_resource,
                    required_scopes=required_scopes,
                )
            ]
        },
    )


def _authorization_challenge(
    *,
    code: str,
    message: str,
    oauth_resource: str,
    required_scopes: list[str],
) -> str:
    parameters = [
        f'resource_metadata="{_quote_auth_parameter(_resource_metadata_url(oauth_resource))}"',
        f'error="{"insufficient_scope" if code == "SCOPE_REQUIRED" else "invalid_token"}"',
        f'error_description="{_quote_auth_parameter(message)}"',
    ]
    if required_scopes:
        parameters.append(f'scope="{_quote_auth_parameter(" ".join(required_scopes))}"')
    return "Bearer " + ", ".join(parameters)


def _resource_metadata_url(oauth_resource: str) -> str:
    parsed = urlsplit(oauth_resource)
    resource_path = parsed.path.rstrip("/")
    return f"{parsed.scheme}://{parsed.netloc}/.well-known/oauth-protected-resource{resource_path}"


def _quote_auth_parameter(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _error(
    code: str,
    message: str,
    request_id: str,
    details: dict[str, str | int | bool] | None = None,
    *,
    schema_version: _McpSchemaVersion = "2.0",
) -> str:
    return json.dumps(
        {
            "schema_version": schema_version,
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


def _result_with_schema_version(result: McpResult, schema_version: _McpSchemaVersion) -> McpResult:
    """Return a server-mode envelope without mutating the service result."""

    if result.schema_version == schema_version:
        return result
    return result.model_copy(update={"schema_version": schema_version})


def _as_v2_result(result: McpResult) -> McpResultV2:
    """Narrow a boundary result to the exact schema advertised by v2 tools."""

    # OAuth challenges are returned as CallToolResult so the MCP transport can
    # attach WWW-Authenticate metadata. Preserve that special transport result;
    # the structured envelope it carries was already created as schema v2.
    if isinstance(result, CallToolResult):
        return cast(McpResultV2, result)
    return McpResultV2.model_validate(result.model_dump(mode="python"))


def _safe_request_id(value: str) -> str:
    if len(value) <= 100 and all(character.isalnum() or character in "-_.:" for character in value):
        return value
    return f"req_{hashlib.sha256(value.encode()).hexdigest()}"
