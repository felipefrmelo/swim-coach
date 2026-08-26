"""Read-only, user-scoped query service for the P05 MCP surface."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from time import perf_counter
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field

from swim_coach.application.ports.repositories import UnitOfWorkFactory
from swim_coach.application.services.activity_data import ActivityDataService
from swim_coach.application.services.context import ContextService
from swim_coach.application.services.identity import IdentityService
from swim_coach.application.services.workouts import WorkoutDetail, WorkoutService
from swim_coach.domain.activities import coefficient_of_variation
from swim_coach.domain.garmin import Activity
from swim_coach.domain.goals import GoalStatus, TrainingGoal
from swim_coach.domain.operations import McpToolInvocation
from swim_coach.domain.shared.errors import DomainError, ResourceNotFoundError
from swim_coach.domain.shared.types import JsonObject
from swim_coach.domain.shared.value_objects import CorrelationId, EntityId, UserId

MCP_READ_SCOPES = (
    "profile:read",
    "goals:read",
    "workouts:read",
    "activities:read",
    "analytics:read",
    "sync:read",
)
MCP_READ_TOOL_SCOPES: dict[str, tuple[str, ...]] = {
    "get_capabilities": (),
    "get_training_context": ("profile:read", "goals:read"),
    "get_today_workout": ("workouts:read",),
    "get_week_plan": ("workouts:read",),
    "list_recent_swims": ("activities:read",),
    "get_swim_activity": ("activities:read", "analytics:read"),
    "get_goal_progress": ("goals:read", "analytics:read"),
    "get_sync_status": ("sync:read",),
}
MCP_READ_TOOLS = tuple(MCP_READ_TOOL_SCOPES)


class McpModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class McpWarning(McpModel):
    code: str
    message: str


class McpNextAction(McpModel):
    action: str
    reason: str


class McpResult(McpModel):
    schema_version: Literal["1.0"] = "1.0"
    request_id: str
    status: Literal["OK", "PARTIAL", "NOT_FOUND"]
    data: dict[str, Any]
    warnings: list[McpWarning] = Field(default_factory=list)
    next_actions: list[McpNextAction] = Field(default_factory=list)
    human_summary: str


@dataclass(frozen=True, slots=True)
class McpPrincipal:
    user_id: UserId
    subject: str
    scopes: frozenset[str]


class McpReadService:
    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory,
        identity: IdentityService,
        context: ContextService,
        workouts: WorkoutService,
        activity_data: ActivityDataService,
    ) -> None:
        self._uow_factory = uow_factory
        self._identity = identity
        self._context = context
        self._workouts = workouts
        self._activity_data = activity_data

    async def resolve_principal(
        self, *, subject: str, scopes: list[str], required_scopes: frozenset[str]
    ) -> McpPrincipal:
        granted = frozenset(scopes)
        missing = sorted(required_scopes - granted)
        if missing:
            raise DomainError(
                "SCOPE_REQUIRED",
                "Additional authorization scope is required.",
                details={"scope": " ".join(missing)},
            )
        user = await self._identity.resolve_identity(provider="oidc", subject=subject)
        return McpPrincipal(user.id, subject, granted)

    async def get_capabilities(self, request_id: str) -> McpResult:
        return McpResult(
            request_id=request_id,
            status="OK",
            data={
                "server_name": "swim-coach",
                "server_version": "0.1.0-read-only",
                "phase": "P05",
                "release_mode": "authenticated-read-only",
                "available_tools": list(MCP_READ_TOOLS),
                "required_scopes": list(MCP_READ_SCOPES),
                "transport": "streamable-http",
                "private_training_data_enabled": True,
                "garmin_sync_via_tool_enabled": False,
                "garmin_write_enabled": False,
                "custom_ui_enabled": False,
            },
            human_summary=(
                "Swim Coach exposes authenticated read-only training context, workouts, "
                "swims, goal progress, and sync status. No tool can write or call Garmin."
            ),
        )

    async def get_training_context(
        self, principal: McpPrincipal, request_id: str, *, include_constraints: bool
    ) -> McpResult:
        me = await self._context.get_me(principal.user_id)
        pools = await self._context.list_pools(principal.user_id)
        availability = await self._context.list_availability(principal.user_id)
        goals = await self._context.list_goals(principal.user_id)
        async with self._uow_factory() as uow:
            constraints = (
                await uow.constraints.list(principal.user_id) if include_constraints else []
            )
        active_goal = next((item for item in goals if item.status is GoalStatus.ACTIVE), None)
        default_pool_length = next((p.length.meters for p in pools if p.is_default), 20)
        return McpResult(
            request_id=request_id,
            status="OK",
            data={
                "profile": {
                    "locale": me.user.locale,
                    "timezone": me.user.timezone,
                    "experience_level": me.profile.experience_level,
                    "default_sessions_per_week": me.profile.default_sessions_per_week,
                },
                "pools": [
                    {
                        "pool_id": str(item.id),
                        "length_m": item.length.meters,
                        "default": item.is_default,
                    }
                    for item in pools
                    if item.active
                ],
                "active_goal": self._goal(active_goal) if active_goal else None,
                "availability": [
                    {
                        "day_of_week": item.day_of_week,
                        "start_local_time": item.start_local_time.isoformat(timespec="minutes"),
                        "end_local_time": item.end_local_time.isoformat(timespec="minutes"),
                        "max_duration_minutes": item.max_duration_minutes,
                    }
                    for item in availability[:14]
                ],
                "constraints": [
                    {
                        "type": item.constraint_type.value,
                        "severity": item.severity,
                        "active_from": item.active_from.isoformat(),
                        "active_until": item.active_until.isoformat()
                        if item.active_until
                        else None,
                    }
                    for item in constraints
                    if item.is_active
                ][:20],
            },
            human_summary=(
                f"Training context uses a {default_pool_length} m "
                f"pool and {me.profile.default_sessions_per_week} planned sessions per week."
            ),
        )

    async def get_today_workout(
        self,
        principal: McpPrincipal,
        request_id: str,
        *,
        target_date: date | None,
        include_steps: bool,
        include_publish_status: bool,
    ) -> McpResult:
        me = await self._context.get_me(principal.user_id)
        local_date = (
            target_date or datetime.now(UTC).astimezone(self._timezone(me.user.timezone)).date()
        )
        details = list(await self._workouts.list_workouts(principal.user_id))
        detail = next(
            (
                item
                for item in details
                if item.schedule and item.schedule.scheduled_date == local_date
            ),
            None,
        )
        if detail is None:
            return McpResult(
                request_id=request_id,
                status="NOT_FOUND",
                data={"date": local_date.isoformat(), "workout": None},
                human_summary=f"No pool workout is scheduled for {local_date.isoformat()}.",
            )
        return McpResult(
            request_id=request_id,
            status="OK",
            data={
                "date": local_date.isoformat(),
                "workout": self._workout(detail, include_steps, include_publish_status),
            },
            human_summary=(
                f"{detail.workout.title}: {detail.current_revision.totals.distance_m} m scheduled "
                f"for {local_date.isoformat()}."
            ),
        )

    async def get_week_plan(
        self, principal: McpPrincipal, request_id: str, *, week_start: date | None
    ) -> McpResult:
        me = await self._context.get_me(principal.user_id)
        today = datetime.now(UTC).astimezone(self._timezone(me.user.timezone)).date()
        start = week_start or today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)
        details = await self._workouts.list_workouts(principal.user_id)
        selected = [
            item
            for item in details
            if item.schedule and start <= item.schedule.scheduled_date <= end
        ]
        selected.sort(key=lambda item: item.schedule.scheduled_date if item.schedule else start)
        total_distance = sum(item.current_revision.totals.distance_m for item in selected)
        return McpResult(
            request_id=request_id,
            status="OK",
            data={
                "week_start": start.isoformat(),
                "week_end": end.isoformat(),
                "session_count": len(selected),
                "total_distance_m": total_distance,
                "sessions": [self._workout(item, False, True) for item in selected],
            },
            human_summary=f"Week has {len(selected)} scheduled swims totaling {total_distance} m.",
        )

    async def get_workouts(
        self,
        principal: McpPrincipal,
        request_id: str,
        *,
        workout_id: EntityId | None,
        target_date: date | None,
        week_start: date | None,
        include_steps: bool,
    ) -> McpResult:
        details = list(await self._workouts.list_workouts(principal.user_id))
        if workout_id is not None:
            details = [item for item in details if item.workout.id == workout_id]
        elif target_date is not None:
            details = [
                item
                for item in details
                if item.schedule is not None and item.schedule.scheduled_date == target_date
            ]
        elif week_start is not None:
            week_end = week_start + timedelta(days=6)
            details = [
                item
                for item in details
                if item.schedule is not None
                and week_start <= item.schedule.scheduled_date <= week_end
            ]
        details.sort(
            key=lambda item: (
                item.schedule.scheduled_date if item.schedule else date.max,
                item.workout.created_at,
            )
        )
        items = [self._workout(item, include_steps, True) for item in details]
        for item in items:
            item.pop("content_hash", None)
        return McpResult(
            request_id=request_id,
            status="OK" if items else "NOT_FOUND",
            data={"items": items, "count": len(items)},
            human_summary=f"Found {len(items)} matching swim workout(s).",
        )

    async def list_recent_swims(
        self,
        principal: McpPrincipal,
        request_id: str,
        *,
        limit: int,
        before: datetime | None,
        include_analysis_summary: bool,
    ) -> McpResult:
        async with self._uow_factory() as uow:
            activities = await uow.activities.list_recent(
                principal.user_id, limit=limit, before=before
            )
            analyses = (
                await uow.activity_data.list_analyses(
                    principal.user_id, [item.id for item in activities]
                )
                if include_analysis_summary
                else []
            )
            metrics_by_activity = {item.activity_id: item.metrics for item in analyses}
            items = [
                self._activity(activity, metrics_by_activity.get(activity.id))
                for activity in activities
            ]
        next_cursor = (
            activities[-1].start_time_utc.isoformat() if len(activities) == limit else None
        )
        return McpResult(
            request_id=request_id,
            status="OK",
            data={"items": items, "next_before": next_cursor, "limit": limit},
            human_summary=f"Found {len(items)} recent pool swims in local storage.",
        )

    async def get_swim_activity(
        self,
        principal: McpPrincipal,
        request_id: str,
        *,
        activity_id: EntityId,
        include_intervals: bool,
        include_lengths: bool,
        max_intervals: int,
    ) -> McpResult:
        detail = await self._activity_data.get(principal.user_id, activity_id)
        normalized = detail.normalized
        intervals = (
            list(normalized.intervals)[:max_intervals] if normalized and include_intervals else []
        )
        lengths = list(normalized.lengths)[:100] if normalized and include_lengths else []
        warnings = []
        if normalized is None:
            warnings.append(
                McpWarning(code="DATA_INCOMPLETE", message="FIT normalization is unavailable.")
            )
        elif include_intervals and len(normalized.intervals) > max_intervals:
            warnings.append(
                McpWarning(code="RESULT_TRUNCATED", message="Intervals were truncated.")
            )
        if normalized and include_lengths and len(normalized.lengths) > 100:
            warnings.append(
                McpWarning(code="RESULT_TRUNCATED", message="Lengths were truncated at 100.")
            )
        return McpResult(
            request_id=request_id,
            status="PARTIAL" if warnings else "OK",
            data={
                **self._activity(
                    detail.activity, detail.analysis.metrics if detail.analysis else None
                ),
                "quality": normalized.normalization.quality.value if normalized else None,
                "completeness": self._number(normalized.normalization.completeness)
                if normalized
                else None,
                "analysis": dict(detail.analysis.metrics) if detail.analysis else None,
                "analysis_flags": list(detail.analysis.flags) if detail.analysis else [],
                "intervals": [
                    {
                        "index": item.interval_index,
                        "type": item.interval_type,
                        "distance_m": item.distance_m,
                        "duration_seconds": self._number(item.duration_seconds),
                        "rest_seconds": self._number(item.rest_seconds),
                        "pace_seconds_per_100m": self._number(item.pace_seconds_per_100m),
                        "stroke_type": self._safe_text(item.stroke_type, 50),
                        "swolf": self._number(item.swolf),
                    }
                    for item in intervals
                ],
                "lengths": [
                    {
                        "index": item.length_index,
                        "distance_m": item.distance_m,
                        "duration_seconds": self._number(item.duration_seconds),
                        "stroke_type": self._safe_text(item.stroke_type, 50),
                        "swolf": self._number(item.swolf),
                    }
                    for item in lengths
                ],
                "match": (
                    {
                        "planned_workout_id": str(detail.match.planned_workout_id),
                        "confidence": self._number(detail.match.confidence),
                        "method": detail.match.method,
                    }
                    if detail.match
                    else None
                ),
                "feedback": (
                    {
                        "rpe": detail.feedback.rpe,
                        "technique_rating": detail.feedback.technique_rating,
                        "fatigue_rating": detail.feedback.fatigue_rating,
                        "pain_present": detail.feedback.pain_present,
                    }
                    if detail.feedback
                    else None
                ),
            },
            warnings=warnings,
            human_summary=(
                f"Swim covered {detail.activity.distance.meters} m in "
                f"{self._number(detail.activity.moving.seconds)} moving seconds."
            ),
        )

    async def get_goal_progress(
        self, principal: McpPrincipal, request_id: str, *, goal_id: EntityId | None
    ) -> McpResult:
        async with self._uow_factory() as uow:
            goals = await uow.goals.list(principal.user_id)
            goal = (
                await uow.goals.get(principal.user_id, goal_id)
                if goal_id
                else next((item for item in goals if item.status is GoalStatus.ACTIVE), None)
            )
            if goal is None:
                raise ResourceNotFoundError("goal")
            activities = await uow.activities.list_recent(principal.user_id, limit=20)
            analyses = await uow.activity_data.list_analyses(
                principal.user_id, [item.id for item in activities]
            )
            metrics_by_activity = {item.activity_id: item.metrics for item in analyses}
            samples = [
                (activity, metrics_by_activity[activity.id])
                for activity in activities
                if activity.id in metrics_by_activity
            ]
        best_distance = max((item.distance.meters for item, _ in samples), default=0)
        paces = [
            Decimal(str(metrics["average_pace_seconds_per_100m"]))
            for _, metrics in samples
            if metrics.get("average_pace_seconds_per_100m") is not None
        ]
        best_pace = min(paces, default=None)
        target_distance = goal.target_distance.meters
        target_pace = goal.target_pace.seconds_per_100m
        distance_ratio = (
            Decimal(best_distance) / Decimal(target_distance) if target_distance else None
        )
        pace_gap = best_pace - target_pace if best_pace is not None else None
        pace_ratio = target_pace / best_pace if best_pace is not None else None
        pace_variation = coefficient_of_variation(tuple(paces))
        consistency_score = (
            max(Decimal(0), Decimal(1) - min(pace_variation, Decimal(1)))
            if pace_variation is not None
            else None
        )
        confidence_score = min(Decimal(1), Decimal(len(samples)) / Decimal(8))
        confidence_level = (
            "HIGH"
            if len(samples) >= 8
            else "MODERATE"
            if len(samples) >= 3
            else "LOW"
            if samples
            else "NONE"
        )
        return McpResult(
            request_id=request_id,
            status="OK" if samples else "PARTIAL",
            data={
                "goal": self._goal(goal),
                "sample_size": len(samples),
                "best_recent_distance_m": best_distance,
                "best_recent_pace_seconds_per_100m": self._number(best_pace),
                "distance_completion_ratio": self._number(distance_ratio),
                "pace_gap_seconds_per_100m": self._number(pace_gap),
                "sample_quality": "GOOD" if len(samples) >= 3 else "LIMITED",
                "dimensions": {
                    "endurance": {
                        "best_recent_distance_m": best_distance,
                        "target_distance_m": target_distance,
                        "completion_ratio": self._number(distance_ratio),
                        "status": (
                            "ACHIEVED"
                            if distance_ratio is not None and distance_ratio >= 1
                            else "IN_PROGRESS"
                        ),
                    },
                    "pace": {
                        "best_recent_seconds_per_100m": self._number(best_pace),
                        "target_seconds_per_100m": self._number(target_pace),
                        "gap_seconds_per_100m": self._number(pace_gap),
                        "achievement_ratio": self._number(pace_ratio),
                        "status": (
                            "ACHIEVED"
                            if best_pace is not None and best_pace <= target_pace
                            else "IN_PROGRESS"
                        ),
                    },
                    "consistency": {
                        "analyzed_swims": len(samples),
                        "pace_coefficient_of_variation": self._number(pace_variation),
                        "score": self._number(consistency_score),
                        "status": "AVAILABLE" if consistency_score is not None else "LIMITED",
                    },
                    "confidence": {
                        "sample_size": len(samples),
                        "score": self._number(confidence_score),
                        "level": confidence_level,
                    },
                },
            },
            warnings=(
                []
                if samples
                else [
                    McpWarning(code="DATA_INCOMPLETE", message="No analyzed swims are available.")
                ]
            ),
            human_summary=(
                f"Goal progress is based on {len(samples)} analyzed swims; best recent distance "
                f"is {best_distance} m."
            ),
        )

    async def get_sync_status(self, principal: McpPrincipal, request_id: str) -> McpResult:
        async with self._uow_factory() as uow:
            connection = await uow.garmin_connections.get(principal.user_id)
            runs = await uow.sync_runs.list_recent(principal.user_id, limit=5)
        last_success = next((item for item in runs if item.finished_at and item.failed == 0), None)
        stale = True
        if last_success and last_success.finished_at:
            stale = datetime.now(UTC) - last_success.finished_at > timedelta(hours=24)
        connection_label = connection.status.value if connection else "not connected"
        return McpResult(
            request_id=request_id,
            status="OK",
            data={
                "connection_status": connection.status.value if connection else "not_connected",
                "last_success_at": (
                    last_success.finished_at.isoformat()
                    if last_success and last_success.finished_at
                    else None
                ),
                "stale": stale,
                "recent_runs": [
                    {
                        "status": item.status.value,
                        "listed": item.listed,
                        "created": item.created,
                        "updated": item.updated,
                        "skipped": item.skipped,
                        "failed": item.failed,
                        "started_at": item.started_at.isoformat(),
                        "finished_at": item.finished_at.isoformat() if item.finished_at else None,
                        "error_code": item.error.get("code") if item.error else None,
                    }
                    for item in runs
                ],
                "sync_can_be_started_from_mcp": False,
            },
            human_summary=(
                f"Garmin connection is {connection_label}; "
                f"locally stored data is {'stale' if stale else 'fresh'}."
            ),
        )

    async def record_invocation(
        self,
        *,
        principal: McpPrincipal,
        tool_name: str,
        request_id: str,
        arguments: dict[str, Any],
        started_at: float,
        outcome: str,
        correlation_id: CorrelationId | None = None,
        causation_id: EntityId | None = None,
        error_code: str | None = None,
    ) -> None:
        encoded = json.dumps(arguments, sort_keys=True, separators=(",", ":"), default=str).encode()
        invocation = McpToolInvocation(
            id=EntityId.new(),
            user_id=principal.user_id,
            tool_name=tool_name,
            request_id=request_id,
            args_hash=hashlib.sha256(encoded).hexdigest(),
            outcome=outcome,
            latency_ms=max(0, round((perf_counter() - started_at) * 1_000)),
            correlation_id=correlation_id,
            causation_id=causation_id,
            error_code=error_code,
        )
        async with self._uow_factory() as uow:
            await uow.mcp_tool_invocations.add(invocation)
            await uow.commit()

    @staticmethod
    def _workout(
        detail: WorkoutDetail, include_steps: bool, include_publish_status: bool
    ) -> dict[str, Any]:
        revision = detail.current_revision
        data: dict[str, Any] = {
            "workout_id": str(detail.workout.id),
            "revision": revision.revision_number,
            "title": McpReadService._safe_text(detail.workout.title, 160),
            "purpose": detail.workout.purpose,
            "status": detail.workout.status.value,
            "scheduled_date": detail.schedule.scheduled_date.isoformat()
            if detail.schedule
            else None,
            "scheduled_local_time": (
                detail.schedule.scheduled_start_time.isoformat(timespec="minutes")
                if detail.schedule and detail.schedule.scheduled_start_time
                else None
            ),
            "pool_length_m": revision.definition.pool_length_m,
            "totals": {
                "distance_m": revision.totals.distance_m,
                "estimated_active_seconds": revision.totals.active_seconds,
                "estimated_rest_seconds": revision.totals.rest_seconds,
                "estimated_total_seconds": revision.totals.estimated_total_seconds,
            },
            "content_hash": f"sha256:{revision.content_hash}",
        }
        if include_publish_status:
            data["garmin"] = {
                "publish_status": "PUBLISHED"
                if detail.workout.status.value == "published"
                else "NOT_PUBLISHED"
            }
        if include_steps:
            data["steps"] = McpReadService._steps(revision.definition.nodes)
        return data

    @staticmethod
    def _steps(nodes: tuple[Any, ...]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for node in nodes[:100]:
            if node.type == "repeat":
                result.append(
                    {
                        "type": "repeat",
                        "repetitions": node.repetitions,
                        "label": McpReadService._safe_text(node.label, 160),
                        "children": McpReadService._steps(node.children),
                    }
                )
                continue
            result.append(
                {
                    "type": "step",
                    "role": node.step_role,
                    "label": McpReadService._safe_text(node.label, 160),
                    "end_condition": node.end_condition.model_dump(mode="json"),
                    "target": node.target.model_dump(mode="json"),
                    "stroke": node.stroke.model_dump(mode="json"),
                    "intensity": node.intensity,
                    "equipment": list(node.equipment),
                    "instructions": McpReadService._safe_text(node.instructions, 300),
                }
            )
        return result

    @staticmethod
    def _activity(activity: Activity, metrics: JsonObject | None) -> dict[str, Any]:
        local_started = activity.start_time_utc.astimezone(
            McpReadService._timezone(activity.timezone)
        )
        return {
            "activity_id": str(activity.id),
            "started_local": local_started.isoformat(),
            "distance_m": activity.distance.meters,
            "elapsed_seconds": McpReadService._number(activity.elapsed.seconds),
            "moving_seconds": McpReadService._number(activity.moving.seconds),
            "pace_seconds_per_100m": McpReadService._number(
                metrics.get("average_pace_seconds_per_100m")
                if metrics
                else activity.avg_pace_seconds_per_100m
            ),
            "pool_length_m": activity.pool_length.meters if activity.pool_length else None,
            "analysis_summary": (
                {
                    "consistency_cv": metrics.get("consistency_cv"),
                    "fade_percent": metrics.get("fade_percent"),
                    "average_swolf": metrics.get("average_swolf"),
                    "completeness": metrics.get("completeness"),
                }
                if metrics
                else None
            ),
        }

    @staticmethod
    def _goal(goal: TrainingGoal | None) -> dict[str, Any] | None:
        if goal is None:
            return None
        return {
            "goal_id": str(goal.id),
            "title": McpReadService._safe_text(goal.title, 160),
            "status": goal.status.value,
            "target_distance_m": goal.target_distance.meters,
            "target_duration_seconds": McpReadService._number(goal.target_duration.seconds),
            "target_pace_seconds_per_100m": McpReadService._number(
                goal.target_pace.seconds_per_100m
            ),
            "target_date": goal.target_date.isoformat() if goal.target_date else None,
        }

    @staticmethod
    def _safe_text(value: str | None, limit: int) -> str | None:
        if value is None:
            return None
        cleaned = " ".join(value.replace("\x00", " ").split())
        return cleaned[:limit]

    @staticmethod
    def _number(value: Any | None) -> int | float | None:
        if value is None:
            return None
        decimal = Decimal(str(value))
        return int(decimal) if decimal == decimal.to_integral() else float(decimal)

    @staticmethod
    def _timezone(value: str) -> ZoneInfo:
        try:
            return ZoneInfo(value)
        except ZoneInfoNotFoundError:
            return ZoneInfo("UTC")
