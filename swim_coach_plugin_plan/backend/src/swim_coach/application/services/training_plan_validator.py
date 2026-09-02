"""Deterministic integrity validation for coach-authored training plans."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import ValidationError

from swim_coach.domain.athlete import AvailabilityRule, Pool
from swim_coach.domain.planning import (
    PlanDetailLevel,
    PlanSessionBinding,
    TrainingPlanDocument,
)
from swim_coach.domain.shared.errors import DomainError
from swim_coach.domain.shared.types import JsonObject
from swim_coach.domain.workouts import CanonicalWorkout, validate_workout


@dataclass(frozen=True, slots=True)
class TrainingPlanValidationContext:
    timezone: str
    pools: tuple[Pool, ...]
    availability: tuple[AvailabilityRule, ...]


class TrainingPlanValidator:
    """Validate objective constraints without changing the coach prescription."""

    def validate(
        self,
        document: TrainingPlanDocument,
        context: TrainingPlanValidationContext,
        *,
        previous: TrainingPlanDocument | None = None,
        bindings: tuple[PlanSessionBinding, ...] = (),
        immutable_session_ids: frozenset[str] = frozenset(),
        reviewed_week: int | None = None,
        revision_kind: str | None = None,
        local_today: date | None = None,
    ) -> None:
        issues: list[JsonObject] = []
        if document.schema_version == "2.0" and (
            document.baseline_snapshot or document.baseline_confidence.value != "LOW"
        ):
            issues.append(
                self._issue(
                    "MEASURED_EVIDENCE_OUTSIDE_PLAN_INTENT",
                    "definition.baseline_snapshot",
                    "Measured evidence belongs to reviews and coach context, not plan intent.",
                )
            )
        if document.timezone != context.timezone:
            issues.append(
                self._issue(
                    "TIMEZONE_MISMATCH",
                    "definition.timezone",
                    "Plan timezone must match the athlete profile timezone.",
                    value=document.timezone,
                    expected=context.timezone,
                )
            )
        try:
            ZoneInfo(context.timezone)
        except ZoneInfoNotFoundError:
            issues.append(
                self._issue(
                    "INVALID_TIMEZONE",
                    "definition.timezone",
                    "Athlete profile timezone is not a valid IANA timezone.",
                    value=context.timezone,
                )
            )

        start_date = document.start_date
        if start_date is None:
            issues.append(
                self._issue(
                    "PLAN_START_DATE_REQUIRED",
                    "definition.start_date",
                    "Coach-defined plans require start_date.",
                )
            )
        elif start_date.weekday() != 0:
            issues.append(
                self._issue(
                    "PLAN_START_NOT_MONDAY",
                    "definition.start_date",
                    "Plan start_date must be a Monday.",
                    value=start_date.isoformat(),
                )
            )

        active_pools = {str(item.id): item for item in context.pools if item.active}
        scheduled_slots: set[tuple[str, str]] = set()
        for week_index, week in enumerate(document.weeks):
            week_path = f"definition.weeks[{week_index}]"
            week_start = (
                start_date + timedelta(days=(week.week_number - 1) * 7)
                if start_date is not None
                else None
            )
            week_end = week_start + timedelta(days=6) if week_start is not None else None
            for session_index, session in enumerate(week.sessions):
                session_path = f"{week_path}.sessions[{session_index}]"
                if (
                    session.scheduled_date is not None
                    and week_start is not None
                    and week_end is not None
                ):
                    if not week_start <= session.scheduled_date <= week_end:
                        issues.append(
                            self._issue(
                                "SESSION_OUTSIDE_PLAN_WEEK",
                                f"{session_path}.scheduled_date",
                                "Session date must fall inside its declared plan week.",
                                value=session.scheduled_date.isoformat(),
                            )
                        )
                if week.detail_level is PlanDetailLevel.DETAILED:
                    self._validate_detailed_session(
                        session,
                        session_path,
                        active_pools,
                        context.availability,
                        scheduled_slots,
                        issues,
                    )
            if week.detail_level is PlanDetailLevel.DETAILED:
                prescribed_distance = sum(
                    session.target_distance_m or 0 for session in week.sessions
                )
                prescribed_duration = sum(
                    session.planned_duration_minutes or 0 for session in week.sessions
                )
                self._validate_week_total(
                    prescribed_distance,
                    week.target_distance_min_m,
                    week.target_distance_max_m,
                    f"{week_path}.target_distance_min_m",
                    "WEEK_DISTANCE_TARGET_MISMATCH",
                    "Detailed session distance must fit the coach-authored weekly range.",
                    issues,
                )
                self._validate_week_total(
                    prescribed_duration,
                    week.target_duration_min_minutes,
                    week.target_duration_max_minutes,
                    f"{week_path}.target_duration_min_minutes",
                    "WEEK_DURATION_TARGET_MISMATCH",
                    "Detailed session duration must fit the coach-authored weekly range.",
                    issues,
                )

        if previous is not None:
            self._validate_revision(
                previous,
                document,
                bindings=bindings,
                immutable_session_ids=immutable_session_ids,
                reviewed_week=reviewed_week,
                revision_kind=revision_kind,
                local_today=local_today,
                issues=issues,
            )
        if issues:
            raise DomainError(
                "PLAN_VALIDATION_FAILED",
                "The coach-authored training plan is invalid.",
                details=cast(JsonObject, {"issues": issues}),
            )

    def _validate_detailed_session(
        self,
        session: Any,
        path: str,
        active_pools: dict[str, Pool],
        availability: tuple[AvailabilityRule, ...],
        scheduled_slots: set[tuple[str, str]],
        issues: list[JsonObject],
    ) -> None:
        if session.scheduled_date is None or session.scheduled_start_time is None:
            return
        slot = (
            session.scheduled_date.isoformat(),
            session.scheduled_start_time.isoformat(timespec="minutes"),
        )
        if slot in scheduled_slots:
            issues.append(
                self._issue(
                    "DUPLICATE_SESSION_SCHEDULE",
                    f"{path}.scheduled_start_time",
                    "Two sessions cannot occupy the same local start time.",
                    value=f"{slot[0]}T{slot[1]}",
                )
            )
        scheduled_slots.add(slot)

        pool = active_pools.get(session.pool_id or "")
        if pool is None:
            issues.append(
                self._issue(
                    (
                        "SESSION_POOL_REQUIRED"
                        if session.pool_id is None
                        else "SESSION_POOL_NOT_AVAILABLE"
                    ),
                    f"{path}.pool_id",
                    "A detailed session must identify an active athlete pool.",
                    value=session.pool_id,
                )
            )

        duration = session.planned_duration_minutes
        matching_rules = [
            item
            for item in availability
            if item.day_of_week == session.scheduled_date.weekday()
            and (item.valid_from is None or item.valid_from <= session.scheduled_date)
            and (item.valid_until is None or item.valid_until >= session.scheduled_date)
            and (item.pool_id is None or session.pool_id == str(item.pool_id))
        ]
        schedule_end = (
            datetime.combine(session.scheduled_date, session.scheduled_start_time)
            + timedelta(minutes=duration)
            if duration is not None
            else None
        )
        compatible = [
            item
            for item in matching_rules
            if item.start_local_time <= session.scheduled_start_time < item.end_local_time
            and duration is not None
            and duration <= item.max_duration_minutes
            and schedule_end is not None
            and schedule_end.time() <= item.end_local_time
        ]
        if not matching_rules or not any(
            item.start_local_time <= session.scheduled_start_time < item.end_local_time
            for item in matching_rules
        ):
            issues.append(
                self._issue(
                    "SESSION_OUTSIDE_AVAILABILITY",
                    f"{path}.scheduled_start_time",
                    "Session starts outside the athlete's registered availability.",
                    value=session.scheduled_start_time.isoformat(timespec="minutes"),
                    weekday=session.scheduled_date.strftime("%A").upper(),
                )
            )
        elif not compatible:
            issues.append(
                self._issue(
                    "SESSION_DURATION_EXCEEDS_AVAILABILITY",
                    f"{path}.planned_duration_minutes",
                    "Session duration does not fit the registered availability window.",
                    value=duration,
                    available_max_minutes=max(item.max_duration_minutes for item in matching_rules),
                )
            )

        if session.workout is None:
            return
        try:
            definition = CanonicalWorkout.model_validate(session.workout)
        except ValidationError as error:
            for item in error.errors(include_url=False):
                suffix = ".".join(str(part) for part in item["loc"])
                issues.append(
                    self._issue(
                        "INVALID_CANONICAL_WORKOUT",
                        f"{path}.workout.{suffix}",
                        str(item["msg"]),
                    )
                )
            return
        validation = validate_workout(definition)
        for validation_issue in validation.errors:
            suffix = validation_issue.path.replace("/", ".").lstrip(".")
            code = (
                "DISTANCE_NOT_POOL_ALIGNED"
                if validation_issue.code == "POOL_DISTANCE_MISMATCH"
                else validation_issue.code
            )
            issue = self._issue(code, f"{path}.workout.{suffix}", validation_issue.message)
            if code == "DISTANCE_NOT_POOL_ALIGNED":
                issue["pool_length_m"] = definition.pool_length_m
                value = self._json_pointer_value(
                    definition.model_dump(mode="json"), validation_issue.path
                )
                if isinstance(value, (str, int, float, bool)):
                    issue["value"] = value
            issues.append(issue)
        if pool is not None and definition.pool_length_m != pool.length.meters:
            issues.append(
                self._issue(
                    "WORKOUT_POOL_LENGTH_MISMATCH",
                    f"{path}.workout.pool_length_m",
                    "Workout pool length must match the selected pool.",
                    value=definition.pool_length_m,
                    expected=pool.length.meters,
                )
            )
        if session.purpose != definition.purpose:
            issues.append(
                self._issue(
                    "WORKOUT_PURPOSE_MISMATCH",
                    f"{path}.workout.purpose",
                    "Session purpose must exactly match the canonical workout purpose.",
                    value=definition.purpose,
                    expected=session.purpose,
                )
            )
        if session.target_distance_m != validation.totals.distance_m:
            issues.append(
                self._issue(
                    "WORKOUT_DISTANCE_MISMATCH",
                    f"{path}.target_distance_m",
                    "Coach target distance must exactly match the canonical workout total.",
                    value=session.target_distance_m,
                    calculated_distance_m=validation.totals.distance_m,
                )
            )
        if duration is not None and validation.totals.estimated_total_seconds > duration * 60:
            issues.append(
                self._issue(
                    "WORKOUT_EXCEEDS_PLANNED_DURATION",
                    f"{path}.planned_duration_minutes",
                    "Deterministically calculable workout time exceeds the planned duration.",
                    value=duration,
                    calculated_seconds=validation.totals.estimated_total_seconds,
                )
            )

    @classmethod
    def _validate_week_total(
        cls,
        value: int,
        minimum: int | None,
        maximum: int | None,
        path: str,
        code: str,
        message: str,
        issues: list[JsonObject],
    ) -> None:
        if (minimum is not None and value < minimum) or (maximum is not None and value > maximum):
            issues.append(
                cls._issue(
                    code,
                    path,
                    message,
                    calculated=value,
                    minimum=minimum,
                    maximum=maximum,
                )
            )

    def _validate_revision(
        self,
        before: TrainingPlanDocument,
        after: TrainingPlanDocument,
        *,
        bindings: tuple[PlanSessionBinding, ...],
        immutable_session_ids: frozenset[str],
        reviewed_week: int | None,
        revision_kind: str | None,
        local_today: date | None,
        issues: list[JsonObject],
    ) -> None:
        immutable_metadata = (
            "goal_id",
            "title",
            "start_date",
            "duration_weeks",
            "timezone",
            "prescription_source",
        )
        for field_name in immutable_metadata:
            if before.schema_version == "1.0" and field_name in {
                "goal_id",
                "title",
                "start_date",
                "timezone",
                "prescription_source",
            }:
                continue
            if getattr(before, field_name) != getattr(after, field_name):
                issues.append(
                    self._issue(
                        "PLAN_METADATA_IMMUTABLE",
                        f"definition.{field_name}",
                        "Plan identity metadata cannot change in a revision.",
                    )
                )
        before_sessions = {
            session.session_intent_id: session
            for week in before.weeks
            for session in week.sessions
            if session.session_intent_id is not None
        }
        after_sessions = {
            session.session_intent_id: session
            for week in after.weeks
            for session in week.sessions
            if session.session_intent_id is not None
        }
        protected_ids = set(immutable_session_ids)
        protected_ids.update(str(item.session_intent_id) for item in bindings if item.locked)
        for session_id in protected_ids:
            if before_sessions.get(session_id) != after_sessions.get(session_id):
                issues.append(
                    self._issue(
                        "PLAN_SESSION_LOCKED",
                        f"definition.sessions[{session_id}]",
                        "Completed, skipped, manually edited, or activity-linked "
                        "sessions are immutable.",
                        session_intent_id=session_id,
                    )
                )
        for index, before_week in enumerate(before.weeks):
            week_end = (
                before.start_date + timedelta(days=before_week.week_number * 7 - 1)
                if before.start_date is not None
                else None
            )
            past = local_today is not None and week_end is not None and week_end < local_today
            reviewed = reviewed_week is not None and before_week.week_number <= reviewed_week
            if (past or reviewed) and before_week != after.weeks[index]:
                issues.append(
                    self._issue(
                        "PLAN_PAST_WEEK_IMMUTABLE",
                        f"definition.weeks[{index}]",
                        "Past or reviewed plan weeks cannot be changed.",
                        week_number=before_week.week_number,
                    )
                )
        if revision_kind == "MATERIALIZATION":
            if (
                before.strategy_summary != after.strategy_summary
                or before.review_frequency != after.review_frequency
                or before.phases != after.phases
                or before.baseline_snapshot != after.baseline_snapshot
                or before.baseline_confidence != after.baseline_confidence
            ):
                issues.append(
                    self._issue(
                        "MATERIALIZATION_SCOPE_INVALID",
                        "definition",
                        "Materialization may only replace one future outline or strategic week.",
                    )
                )
            changed = [
                index
                for index, (old, new) in enumerate(zip(before.weeks, after.weeks, strict=True))
                if old != new
            ]
            if len(changed) != 1:
                issues.append(
                    self._issue(
                        "MATERIALIZATION_SCOPE_INVALID",
                        "definition.weeks",
                        "A materialization revision must detail exactly one future week.",
                        changed_week_count=len(changed),
                    )
                )
            elif not (
                before.weeks[changed[0]].detail_level
                in {PlanDetailLevel.OUTLINE, PlanDetailLevel.STRATEGIC}
                and after.weeks[changed[0]].detail_level is PlanDetailLevel.DETAILED
            ):
                issues.append(
                    self._issue(
                        "MATERIALIZATION_TRANSITION_INVALID",
                        f"definition.weeks[{changed[0]}].detail_level",
                        "Materialization must turn one outline or strategic week into a "
                        "coach-authored detailed week.",
                    )
                )

    @staticmethod
    def _issue(code: str, path: str, message: str, **details: Any) -> JsonObject:
        issue: JsonObject = {"code": code, "path": path, "message": message}
        for key, value in details.items():
            if value is not None:
                issue[key] = value
        return issue

    @staticmethod
    def _json_pointer_value(document: Any, pointer: str) -> Any:
        current = document
        for raw_part in pointer.strip("/").split("/"):
            part = raw_part.replace("~1", "/").replace("~0", "~")
            if isinstance(current, list) and part.isdigit():
                current = current[int(part)]
            elif isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return None
        return current
