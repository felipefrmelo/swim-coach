"""Read-only, user-scoped query service for the P05 MCP surface."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from time import perf_counter
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field

from swim_coach.application.ports.repositories import UnitOfWorkFactory
from swim_coach.application.services.activity_data import ActivityDataService
from swim_coach.application.services.activity_views import (
    activity_detail_v2,
    activity_summary_v2,
    analysis_metrics_v1,
    planned_vs_actual_summary_v2,
)
from swim_coach.application.services.context import ContextService
from swim_coach.application.services.equivalent_set_history import (
    historical_equivalent_set_trends,
)
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
    label: str
    required_scope: str | None = None


class McpResult(McpModel):
    # Result envelope v2 makes the activity semantic break detectable.  The
    # canonical workout schema has its own version and intentionally remains
    # at 1.0.
    schema_version: Literal["1.0", "2.0"] = "2.0"
    request_id: str
    status: Literal[
        "OK",
        "ACCEPTED",
        "PARTIAL",
        "NOT_FOUND",
        "NEEDS_INPUT",
        "NEEDS_AUTHORIZATION",
        "CONFLICT",
        "FAILED",
    ]
    data: dict[str, Any]
    warnings: list[McpWarning] = Field(default_factory=list)
    next_actions: list[McpNextAction] = Field(default_factory=list)
    human_summary: str


class McpResultV2(McpResult):
    """Exact public v2 envelope used by MCP output-schema generation."""

    schema_version: Literal["2.0"] = "2.0"


@dataclass(frozen=True, slots=True)
class McpPrincipal:
    user_id: UserId
    subject: str
    scopes: frozenset[str]
    timezone: str | None = None


def _mapping(value: object) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _decimal_value(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except (ValueError, ArithmeticError):
        return None
    return result if result.is_finite() else None


def _integer_value(value: object) -> int | None:
    number = _decimal_value(value)
    return int(number) if number is not None else None


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
        return McpPrincipal(user.id, subject, granted, user.timezone)

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
            normalization_facts = await uow.activity_data.list_current_normalization_facts(
                principal.user_id, [item.id for item in activities]
            )
            normalized_by_activity = {item.activity_id: item for item in normalization_facts}
            analyses = (
                await uow.activity_data.list_analyses(
                    principal.user_id, [item.id for item in activities]
                )
                if include_analysis_summary
                else []
            )
            analyses_by_activity = {item.activity_id: item for item in analyses}
            items = []
            for activity in activities:
                normalization = normalized_by_activity.get(activity.id)
                view = activity_summary_v2(
                    activity,
                    normalization,
                    timezone_name=principal.timezone or activity.timezone,
                )
                analysis = analyses_by_activity.get(activity.id)
                metrics = (
                    analysis.metrics
                    if analysis is not None
                    and normalization is not None
                    and analysis.normalization_id == normalization.id
                    else None
                )
                contextual_paces = _mapping(metrics.get("contextual_paces")) if metrics else None
                view["analysis_summary"] = (
                    {
                        "sets": metrics.get("sets", []),
                        "freestyle_work": (
                            contextual_paces.get("freestyle_work")
                            if contextual_paces is not None
                            else None
                        ),
                        "goal_readiness": metrics.get("goal_readiness"),
                        "planned_vs_actual": planned_vs_actual_summary_v2(
                            metrics.get("planned_vs_actual")
                        ),
                        "data_quality": metrics.get("data_quality"),
                    }
                    if metrics
                    else None
                )
                items.append(view)
        next_cursor = (
            activities[-1].start_time_utc.isoformat() if len(activities) == limit else None
        )
        return McpResult(
            request_id=request_id,
            status="OK",
            data={"items": items, "next_before": next_cursor, "limit": limit},
            human_summary=f"Found {len(items)} recent pool swims in local storage.",
        )

    async def list_recent_swims_v1(
        self,
        principal: McpPrincipal,
        request_id: str,
        *,
        limit: int,
        before: datetime | None,
        include_analysis_summary: bool,
    ) -> McpResult:
        """Project recent swims with the frozen, historically ambiguous v1 fields."""

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
            schema_version="1.0",
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
        view = activity_detail_v2(
            detail,
            timezone_name=principal.timezone or detail.activity.timezone,
        )
        if view["normalization"] is None and not any(
            warning.code == "DATA_INCOMPLETE" for warning in warnings
        ):
            warnings.append(
                McpWarning(
                    code="DATA_INCOMPLETE",
                    message="Canonical FIT normalization is unavailable.",
                )
            )
        if not include_intervals:
            view["intervals"] = []
        else:
            view["intervals"] = view["intervals"][:max_intervals]
        if not include_lengths:
            view["lengths"] = []
        else:
            view["lengths"] = view["lengths"][:100]
        canonical = view["normalization"] is not None
        canonical_distance = view["distance_m"] if canonical else None
        canonical_durations = _mapping(view.get("durations")) if canonical else None
        moving = canonical_durations.get("moving_s") if canonical_durations else None
        swim = canonical_durations.get("swim_s") if canonical_durations else None
        timer = canonical_durations.get("timer_s") if canonical_durations else None
        if moving is not None:
            duration_label = "moving"
            duration = moving
        elif swim is not None:
            duration_label = "swim"
            duration = swim
        else:
            duration_label = "timer"
            duration = timer
        human_summary = (
            f"Swim covered {canonical_distance} m in {duration} {duration_label} seconds."
            if canonical_distance is not None and duration is not None
            else "Canonical FIT normalization is unavailable for this swim."
        )
        return McpResult(
            request_id=request_id,
            status="PARTIAL" if warnings else "OK",
            data=view,
            warnings=warnings,
            human_summary=human_summary,
        )

    async def get_swim_activity_v1(
        self,
        principal: McpPrincipal,
        request_id: str,
        *,
        activity_id: EntityId,
        include_intervals: bool,
        include_lengths: bool,
        max_intervals: int,
    ) -> McpResult:
        """Project one swim exactly as the pre-v2 MCP activity contract did."""

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
            schema_version="1.0",
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
                "analysis": (
                    analysis_metrics_v1(dict(detail.analysis.metrics)) if detail.analysis else None
                ),
                "analysis_flags": list(detail.analysis.flags) if detail.analysis else [],
                "intervals": [
                    {
                        "index": item.interval_index,
                        # Keep the frozen v1 vocabulary even when the stored
                        # normalization was produced by the canonical v2 parser.
                        "type": "rest" if item.interval_type == "rest" else "work",
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
        target_distance = goal.target_distance.meters
        target_pace = goal.target_pace.seconds_per_100m
        goal_specific_minimum = min(400, target_distance)
        evidence_candidates: list[tuple[int, Decimal | None, str, str]] = []
        set_cvs: list[Decimal] = []
        profiles: list[Mapping[str, Any]] = []
        for _activity, metrics in samples:
            readiness = _mapping(metrics.get("goal_readiness"))
            if readiness is not None:
                evidence_distance = _integer_value(readiness.get("longest_evidence_distance_m"))
                evidence_pace = _decimal_value(readiness.get("evidence_pace_s_per_100m"))
                if evidence_distance is not None and evidence_distance > 0:
                    raw_quality = str(readiness.get("confidence") or "LOW").upper()
                    evidence_quality = raw_quality if raw_quality in {"HIGH", "MEDIUM"} else "LOW"
                    evidence_candidates.append(
                        (
                            evidence_distance,
                            evidence_pace,
                            str(readiness.get("evidence_pace_basis") or "unknown"),
                            evidence_quality,
                        )
                    )
            speed_endurance = _mapping(metrics.get("speed_endurance"))
            if speed_endurance is not None:
                profiles.append(speed_endurance)
            raw_sets = metrics.get("sets")
            if isinstance(raw_sets, list):
                for raw_set in raw_sets:
                    set_record = _mapping(raw_set)
                    if set_record is None:
                        continue
                    cv = _decimal_value(set_record.get("coefficient_of_variation"))
                    if cv is not None:
                        set_cvs.append(cv)

        evidence = tuple(item for item in evidence_candidates if item[0] >= goal_specific_minimum)
        short_distance_indicators = tuple(
            item for item in evidence_candidates if item[0] < goal_specific_minimum
        )
        longest_distance = max((item[0] for item in evidence), default=0)
        strongest_candidates = tuple(
            item for item in evidence if item[0] == longest_distance and item[1] is not None
        )
        strongest = min(
            strongest_candidates,
            key=lambda item: item[1] if item[1] is not None else Decimal("Infinity"),
            default=None,
        )
        evidence_pace = strongest[1] if strongest is not None else None
        pace_basis = strongest[2] if strongest is not None else None
        selected_evidence_quality = strongest[3] if strongest is not None else None
        distance_ratio = (
            Decimal(longest_distance) / Decimal(target_distance) if target_distance else None
        )
        pace_gap = evidence_pace - target_pace if isinstance(evidence_pace, Decimal) else None
        pace_ratio = (
            target_pace / evidence_pace
            if isinstance(evidence_pace, Decimal) and evidence_pace > 0
            else None
        )
        mean_set_cv = sum(set_cvs, start=Decimal(0)) / Decimal(len(set_cvs)) if set_cvs else None
        equivalent_set_history = historical_equivalent_set_trends(
            [(activity.start_time_utc, metrics) for activity, metrics in samples]
        )
        consistency_score = (
            max(Decimal(0), Decimal(1) - min(mean_set_cv, Decimal(1)))
            if mean_set_cv is not None
            else None
        )
        sample_factor = min(Decimal(1), Decimal(len(evidence)) / Decimal(6))
        distance_factor = min(
            Decimal(1),
            Decimal(longest_distance) / Decimal(target_distance),
        )
        quality_factor = (
            Decimal(1)
            if selected_evidence_quality == "HIGH"
            else Decimal("0.7")
            if selected_evidence_quality == "MEDIUM"
            else Decimal("0.4")
            if selected_evidence_quality == "LOW"
            else Decimal(0)
        )
        uncapped_confidence_score = (
            sample_factor * Decimal("0.4")
            + distance_factor * Decimal("0.4")
            + quality_factor * Decimal("0.2")
        )
        quality_confidence_cap = (
            Decimal(1)
            if selected_evidence_quality == "HIGH"
            else Decimal("0.79")
            if selected_evidence_quality == "MEDIUM"
            else Decimal("0.49")
            if selected_evidence_quality == "LOW"
            else Decimal(0)
        )
        confidence_score = min(uncapped_confidence_score, quality_confidence_cap)
        calculated_confidence_level = (
            "HIGH"
            if confidence_score >= Decimal("0.8")
            else "MEDIUM"
            if confidence_score >= Decimal("0.5")
            else "LOW"
        )
        confidence_level = (
            "LOW"
            if selected_evidence_quality in {None, "LOW"}
            else "MEDIUM"
            if selected_evidence_quality == "MEDIUM" and calculated_confidence_level == "HIGH"
            else calculated_confidence_level
        )

        def dimension(name: str) -> dict[str, object]:
            records = tuple(
                record
                for profile in profiles
                if (record := _mapping(profile.get(name))) is not None
            )
            best_paces = tuple(
                pace
                for record in records
                if (pace := _decimal_value(record.get("best_pace_s_per_100m"))) is not None
            )
            return {
                "analyzed_sessions": len(records),
                "longest_evidence_distance_m": max(
                    (_integer_value(record.get("longest_distance_m")) or 0 for record in records),
                    default=0,
                ),
                "best_explicit_pace_s_per_100m": self._number(min(best_paces, default=None)),
                "quality_levels": sorted({str(record.get("quality", "LOW")) for record in records}),
            }

        no_goal_specific_evidence = not evidence
        selected_evidence_is_low_quality = selected_evidence_quality == "LOW"
        confidence_reasons = [
            *(["NO_GOAL_SPECIFIC_EVIDENCE"] if no_goal_specific_evidence else []),
            *(["SELECTED_GOAL_EVIDENCE_LOW_QUALITY"] if selected_evidence_is_low_quality else []),
            *(["GOAL_SPECIFIC_PACE_MISSING"] if evidence and strongest is None else []),
        ]
        return McpResult(
            request_id=request_id,
            status=(
                "OK"
                if evidence and strongest is not None and not selected_evidence_is_low_quality
                else "PARTIAL"
            ),
            data={
                "goal": self._goal(goal),
                "sample_size": len(samples),
                "goal_evidence_sample_size": len(evidence),
                "short_distance_indicator_sample_size": len(short_distance_indicators),
                "goal_specific_minimum_distance_m": goal_specific_minimum,
                "longest_goal_evidence_distance_m": longest_distance,
                "goal_evidence_pace_s_per_100m": self._number(evidence_pace),
                "goal_evidence_pace_basis": pace_basis,
                "selected_goal_evidence_quality": selected_evidence_quality,
                "distance_completion_ratio": self._number(distance_ratio),
                "pace_gap_seconds_per_100m": self._number(pace_gap),
                "sample_quality": confidence_level,
                "historical_equivalent_sets": equivalent_set_history,
                "dimensions": {
                    "speed": dimension("speed"),
                    "short_endurance": dimension("short_endurance"),
                    "aerobic_endurance": dimension("aerobic_endurance"),
                    "technique": dimension("technique"),
                    "goal_readiness": {
                        "longest_evidence_distance_m": longest_distance,
                        "target_distance_m": target_distance,
                        "completion_ratio": self._number(distance_ratio),
                        "evidence_pace_s_per_100m": self._number(evidence_pace),
                        "evidence_pace_basis": pace_basis,
                        "target_seconds_per_100m": self._number(target_pace),
                        "gap_seconds_per_100m": self._number(pace_gap),
                        "achievement_ratio": self._number(pace_ratio),
                        "selected_evidence_quality": selected_evidence_quality,
                        "status": (
                            "ACHIEVED"
                            if pace_gap is not None
                            and pace_gap <= 0
                            and longest_distance >= target_distance
                            and not selected_evidence_is_low_quality
                            else "INSUFFICIENT_GOAL_SPECIFIC_EVIDENCE"
                            if no_goal_specific_evidence
                            else "INSUFFICIENT_EVIDENCE_QUALITY"
                            if selected_evidence_is_low_quality
                            else "INSUFFICIENT_GOAL_SPECIFIC_PACE_EVIDENCE"
                            if strongest is None
                            else "IN_PROGRESS"
                        ),
                    },
                    "consistency": {
                        "equivalent_set_samples": len(set_cvs),
                        "mean_equivalent_set_cv": self._number(mean_set_cv),
                        "score": self._number(consistency_score),
                        "status": "AVAILABLE" if consistency_score is not None else "LIMITED",
                    },
                    "confidence": {
                        "sample_size": len(evidence),
                        "score": self._number(confidence_score),
                        "level": confidence_level,
                        "reasons": confidence_reasons,
                    },
                },
            },
            warnings=[
                *(
                    []
                    if samples
                    else [
                        McpWarning(
                            code="DATA_INCOMPLETE",
                            message="No analyzed swims are available.",
                        )
                    ]
                ),
                *(
                    [
                        McpWarning(
                            code="GOAL_EVIDENCE_LIMITED",
                            message=(
                                f"No comparable {goal_specific_minimum} m or longer work "
                                "or continuous evidence is available."
                            ),
                        )
                    ]
                    if samples and no_goal_specific_evidence
                    else []
                ),
            ],
            human_summary=(
                f"No goal-specific evidence meets the {goal_specific_minimum} m minimum; "
                f"{len(short_distance_indicators)} shorter indicator sample(s) remain "
                "available only in the separate speed/endurance dimensions."
                if no_goal_specific_evidence
                else f"Goal progress has {len(evidence)} goal-specific distance sample(s), "
                "but none has usable pace evidence."
                if strongest is None
                else f"Goal progress uses {len(evidence)} goal-specific evidence sample(s); "
                f"the selected {longest_distance} m sample has "
                f"{selected_evidence_quality} quality."
            ),
        )

    async def get_goal_progress_v1(
        self, principal: McpPrincipal, request_id: str, *, goal_id: EntityId | None
    ) -> McpResult:
        """Calculate goal progress with the frozen pre-v2 activity pace semantics."""

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
            schema_version="1.0",
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
