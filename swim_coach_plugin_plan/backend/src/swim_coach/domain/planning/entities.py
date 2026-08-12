"""Pure planning rules, snapshots, decisions and reproducible weekly output."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import StrEnum
from itertools import pairwise
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from swim_coach.domain.identity.entities import utc_now
from swim_coach.domain.shared.errors import DomainError, DomainValidationError
from swim_coach.domain.shared.types import JsonObject
from swim_coach.domain.shared.value_objects import EntityId, UserId
from swim_coach.domain.workouts import (
    CanonicalWorkout,
    DistanceEnd,
    PaceTarget,
    StandardStroke,
    StepNode,
    validate_workout,
)


def canonical_json_hash(value: object) -> str:
    """Hash a JSON-compatible value with a stable encoding."""

    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
    except (TypeError, ValueError) as exc:
        raise DomainValidationError("planning input must be canonical JSON") from exc
    return hashlib.sha256(encoded).hexdigest()


class PlanningModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PlanningRules(PlanningModel):
    schema_version: Literal["1.0"] = "1.0"
    max_sessions_per_week: int = Field(default=3, ge=1, le=7)
    min_hours_between_hard_sessions: int = Field(default=36, ge=12, le=168)
    max_weekly_volume_increase_pct: int = Field(default=8, ge=0, le=20)
    recovery_week_frequency: int = Field(default=4, ge=2, le=12)
    recovery_week_reduction_pct: int = Field(default=20, ge=10, le=50)
    pain_blocks_intensity_at_or_above: int = Field(default=4, ge=1, le=10)
    high_rpe_threshold: int = Field(default=8, ge=6, le=10)
    low_adherence_threshold: float = Field(default=0.75, ge=0, le=1)
    min_session_distance_m: int = Field(default=600, ge=200, le=2_000)
    max_session_distance_m: int = Field(default=3_000, ge=600, le=10_000)
    missed_sessions_do_not_roll_forward_automatically: bool = True
    require_warmup_for_intense_workout: bool = True
    require_cooldown_for_intense_workout: bool = True
    pool_distance_multiple_required: bool = True

    @model_validator(mode="after")
    def validate_distances(self) -> PlanningRules:
        if self.min_session_distance_m > self.max_session_distance_m:
            raise ValueError("minimum session distance must not exceed maximum")
        return self


class AvailabilitySnapshot(PlanningModel):
    date: date
    start_local_time: str
    max_duration_minutes: int = Field(gt=0, le=240)
    pool_id: str


class ConstraintSnapshot(PlanningModel):
    constraint_id: str
    type: str
    severity: int = Field(ge=1, le=5)
    active_from: date
    active_until: date | None = None


class FeedbackSnapshot(PlanningModel):
    activity_id: str
    activity_date: date
    rpe: int = Field(ge=1, le=10)
    technique_rating: int | None = Field(default=None, ge=1, le=5)
    pain_present: bool
    pain_intensity: int | None = Field(default=None, ge=1, le=10)


class RecentWeekSnapshot(PlanningModel):
    week_start: date
    planned_sessions: int = Field(ge=0)
    completed_sessions: int = Field(ge=0)
    completed_distance_m: int = Field(ge=0)
    adherence: float | None = Field(default=None, ge=0, le=1)


class ExistingSessionSnapshot(PlanningModel):
    workout_id: str
    scheduled_date: date
    distance_m: int = Field(ge=0)
    purpose: str


class PlanningPreferences(PlanningModel):
    session_count: int | None = Field(default=None, ge=1, le=7)
    max_session_duration_minutes: int | None = Field(default=None, ge=20, le=120)
    focus: Literal["BALANCED", "TECHNIQUE", "ENDURANCE", "GOAL_PACE"] = "BALANCED"
    avoid_high_intensity: bool = False
    preserve_technique: bool = True


class PlanningContext(PlanningModel):
    user_id: str
    week_start: date
    timezone: str
    pool_id: str
    pool_length_m: int = Field(gt=0, le=200)
    goal_id: str
    goal_version: int = Field(ge=1)
    goal_title: str
    target_distance_m: int = Field(gt=0)
    target_pace_seconds_per_100m: float = Field(gt=0)
    default_sessions_per_week: int = Field(ge=1, le=14)
    availability: tuple[AvailabilitySnapshot, ...]
    constraints: tuple[ConstraintSnapshot, ...] = ()
    recent_feedback: tuple[FeedbackSnapshot, ...] = ()
    recent_weeks: tuple[RecentWeekSnapshot, ...] = ()
    existing_sessions: tuple[ExistingSessionSnapshot, ...] = ()

    @model_validator(mode="after")
    def validate_week(self) -> PlanningContext:
        if self.week_start.weekday() != 0:
            raise ValueError("week_start must be a Monday")
        if any(
            item.date < self.week_start or item.date > self.week_start + timedelta(days=6)
            for item in self.availability
        ):
            raise ValueError("availability must belong to the target week")
        return self


class PlanningDecision(PlanningModel):
    order: int = Field(ge=1)
    decision_type: str
    rule_id: str
    evidence_refs: tuple[str, ...]
    before: JsonObject
    after: JsonObject
    rationale: str


class GeneratedSession(PlanningModel):
    date: date
    start_local_time: str
    session_type: Literal["technique", "aerobic_endurance", "threshold_css", "recovery"]
    distance_m: int = Field(gt=0)
    max_duration_minutes: int = Field(gt=0)
    hard: bool
    workout: JsonObject


class GeneratedWeek(PlanningModel):
    schema_version: Literal["1.0"] = "1.0"
    week_start: date
    week_end: date
    phase: Literal["base", "build", "recovery"]
    target_volume_m: int = Field(gt=0)
    sessions: tuple[GeneratedSession, ...]
    decisions: tuple[PlanningDecision, ...]
    warnings: tuple[str, ...] = ()
    ruleset_version: str
    ruleset_hash: str
    output_hash: str


@dataclass(frozen=True, slots=True)
class TrainingRuleSet:
    id: EntityId
    name: str
    version: str
    rules: PlanningRules
    content_hash: str
    effective_from: date
    effective_until: date | None = None
    schema_version: str = "1.0"
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.version.strip():
            raise DomainValidationError("planning ruleset name and version are required")
        expected = canonical_json_hash(self.rules.model_dump(mode="json"))
        if self.content_hash != expected:
            raise DomainValidationError("planning ruleset content hash does not match")
        if self.effective_until and self.effective_until < self.effective_from:
            raise DomainValidationError("planning ruleset effective range is invalid")


class PlanningRunStatus(StrEnum):
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass(slots=True)
class PlanningRun:
    id: EntityId
    user_id: UserId
    goal_id: EntityId
    rule_set_id: EntityId
    week_start: date
    input_snapshot: JsonObject
    input_hash: str
    output_plan: JsonObject
    status: PlanningRunStatus
    warnings: tuple[str, ...] = ()
    output_proposal_id: EntityId | None = None
    created_at: datetime = field(default_factory=utc_now)
    completed_at: datetime | None = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if self.week_start.weekday() != 0 or len(self.input_hash) != 64:
            raise DomainValidationError("planning run week or input hash is invalid")
        if canonical_json_hash(self.input_snapshot) != self.input_hash:
            raise DomainValidationError("planning run input hash does not match")


@dataclass(frozen=True, slots=True)
class TrainingDecisionRecord:
    id: EntityId
    user_id: UserId
    planning_run_id: EntityId
    order_index: int
    decision_type: str
    rule_id: str
    effective_date: date
    evidence_refs: tuple[str, ...]
    before: JsonObject
    after: JsonObject
    rationale: str
    actor_type: str
    actor_id: str
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if self.order_index < 1 or not self.rule_id.strip() or not self.rationale.strip():
            raise DomainValidationError("training decision is incomplete")


def generate_week(
    context: PlanningContext,
    ruleset: TrainingRuleSet,
    preferences: PlanningPreferences,
) -> GeneratedWeek:
    """Generate the same safe week for the same context, ruleset and preferences."""

    if not context.availability:
        raise DomainError("AVAILABILITY_REQUIRED", "Configure availability for the target week.")
    pool = context.pool_length_m
    if ruleset.rules.pool_distance_multiple_required and any(
        value % pool
        for value in (
            ruleset.rules.min_session_distance_m,
            ruleset.rules.max_session_distance_m,
        )
    ):
        raise DomainError("RULESET_INVALID", "Session limits must match the configured pool.")

    decisions: list[PlanningDecision] = []
    warnings: list[str] = []

    def decide(
        decision_type: str,
        rule_id: str,
        evidence_refs: tuple[str, ...],
        before: JsonObject,
        after: JsonObject,
        rationale: str,
    ) -> None:
        decisions.append(
            PlanningDecision(
                order=len(decisions) + 1,
                decision_type=decision_type,
                rule_id=rule_id,
                evidence_refs=evidence_refs,
                before=before,
                after=after,
                rationale=rationale,
            )
        )

    availability = sorted(
        context.availability,
        key=lambda item: (item.date, item.start_local_time, item.pool_id),
    )
    requested_sessions = preferences.session_count or context.default_sessions_per_week
    session_count = min(
        requested_sessions,
        ruleset.rules.max_sessions_per_week,
        len(availability),
    )
    if session_count < requested_sessions:
        decide(
            "SESSION_COUNT_LIMITED",
            "RULE-AVAILABILITY-001",
            tuple(f"availability:{item.date.isoformat()}" for item in availability),
            {"requested_sessions": requested_sessions},
            {"planned_sessions": session_count},
            "A quantidade de sessões foi limitada pela disponibilidade e pelo ruleset.",
        )
    selected = _spread_slots(availability, session_count)

    pain_evidence = [
        item
        for item in context.recent_feedback
        if item.pain_present
        and (item.pain_intensity or ruleset.rules.pain_blocks_intensity_at_or_above)
        >= ruleset.rules.pain_blocks_intensity_at_or_above
    ]
    active_safety_constraints = [
        item
        for item in context.constraints
        if item.type in {"pain", "injury", "medical_advice"} and item.severity >= 3
    ]
    pain_block = bool(pain_evidence or active_safety_constraints)
    if pain_block:
        warnings.append("PAIN_REVIEW_REQUIRED")
        refs = tuple(
            [f"feedback:{item.activity_id}" for item in pain_evidence]
            + [f"constraint:{item.constraint_id}" for item in active_safety_constraints]
        )
        decide(
            "INTENSITY_BLOCKED",
            "RULE-SAFETY-PAIN-001",
            refs,
            {"high_intensity_allowed": True},
            {"high_intensity_allowed": False},
            (
                "Dor relevante ou restrição ativa bloqueou estímulos intensos; "
                "revisão humana é necessária."
            ),
        )

    recent_rpes = [item.rpe for item in context.recent_feedback]
    mean_rpe = sum(recent_rpes) / len(recent_rpes) if recent_rpes else None
    latest_week = context.recent_weeks[0] if context.recent_weeks else None
    low_adherence = bool(
        latest_week
        and latest_week.adherence is not None
        and latest_week.adherence < ruleset.rules.low_adherence_threshold
    )
    high_fatigue = bool(mean_rpe is not None and mean_rpe >= ruleset.rules.high_rpe_threshold)

    if latest_week and latest_week.completed_sessions < latest_week.planned_sessions:
        decide(
            "MISSED_SESSIONS_NOT_ROLLED_FORWARD",
            "RULE-MISSED-SESSION-001",
            (f"week:{latest_week.week_start.isoformat()}",),
            {
                "planned_sessions": latest_week.planned_sessions,
                "completed_sessions": latest_week.completed_sessions,
            },
            {"rolled_forward_sessions": 0},
            "Sessões perdidas não foram acumuladas automaticamente na semana seguinte.",
        )

    baseline_volume = (
        latest_week.completed_distance_m
        if latest_week and latest_week.completed_distance_m > 0
        else _round_pool(
            context.target_distance_m * session_count * 0.6,
            pool,
        )
    )
    baseline_volume = max(
        baseline_volume,
        _round_pool(ruleset.rules.min_session_distance_m * session_count, pool),
    )
    phase: Literal["base", "build", "recovery"] = "base"
    target_volume = baseline_volume
    if pain_block or high_fatigue or low_adherence:
        target_volume = _round_pool(
            baseline_volume * (100 - ruleset.rules.recovery_week_reduction_pct) / 100,
            pool,
        )
        phase = "recovery"
        decide(
            "LOAD_REDUCED",
            "RULE-RECOVERY-001",
            tuple(
                [f"feedback:{item.activity_id}" for item in context.recent_feedback]
                + ([f"week:{latest_week.week_start.isoformat()}"] if latest_week else [])
            ),
            {"baseline_volume_m": baseline_volume},
            {"target_volume_m": target_volume},
            "A carga foi reduzida por dor, RPE alto ou baixa aderência, sem diagnóstico.",
        )
    elif context.week_start.isocalendar().week % ruleset.rules.recovery_week_frequency == 0:
        target_volume = _round_pool(
            baseline_volume * (100 - ruleset.rules.recovery_week_reduction_pct) / 100,
            pool,
        )
        phase = "recovery"
        decide(
            "RECOVERY_WEEK",
            "RULE-RECOVERY-CYCLE-001",
            (f"week:{context.week_start.isoformat()}",),
            {"baseline_volume_m": baseline_volume},
            {"target_volume_m": target_volume},
            "O ciclo configurado selecionou uma semana de recuperação.",
        )
    elif latest_week and latest_week.adherence is not None and latest_week.adherence >= 0.85:
        target_volume = _round_pool(
            baseline_volume * (100 + ruleset.rules.max_weekly_volume_increase_pct) / 100,
            pool,
        )
        phase = "build"
        decide(
            "VOLUME_PROGRESS_ALLOWED",
            "RULE-VOLUME-CAP-001",
            (f"week:{latest_week.week_start.isoformat()}",),
            {"baseline_volume_m": baseline_volume},
            {"target_volume_m": target_volume},
            "A progressão ficou dentro do teto configurado e depende de boa aderência recente.",
        )
    else:
        decide(
            "VOLUME_MAINTAINED",
            "RULE-CONSERVATIVE-BASELINE-001",
            ("history:limited",),
            {"baseline_volume_m": baseline_volume},
            {"target_volume_m": target_volume},
            "Sem evidência suficiente para progredir, o volume foi mantido conservador.",
        )

    minimum_per_session = _round_pool(ruleset.rules.min_session_distance_m, pool)
    affordable_sessions = max(1, target_volume // minimum_per_session)
    if phase == "recovery" and affordable_sessions < session_count:
        previous_count = session_count
        session_count = affordable_sessions
        selected = _spread_slots(availability, session_count)
        decide(
            "SESSION_COUNT_RECOVERY_LIMITED",
            "RULE-RECOVERY-FREQUENCY-001",
            tuple(f"availability:{item.date.isoformat()}" for item in availability),
            {"planned_sessions": previous_count, "target_volume_m": target_volume},
            {"planned_sessions": session_count, "target_volume_m": target_volume},
            "A frequência foi reduzida para não aumentar a carga durante recuperação.",
        )
    minimum_total = _round_pool(minimum_per_session * session_count, pool)
    target_volume = max(target_volume, minimum_total)
    session_types = _session_types(
        session_count,
        pain_block=pain_block,
        high_fatigue=high_fatigue,
        avoid_high_intensity=preferences.avoid_high_intensity,
        focus=preferences.focus,
    )
    if (
        latest_week
        and session_count > latest_week.planned_sessions
        and "threshold_css" in session_types
    ):
        session_types = [
            "aerobic_endurance" if item == "threshold_css" else item for item in session_types
        ]
        decide(
            "INTENSITY_HELD",
            "RULE-SINGLE-PROGRESSION-001",
            (f"week:{latest_week.week_start.isoformat()}",),
            {"frequency": latest_week.planned_sessions, "intensity": "threshold"},
            {"frequency": session_count, "intensity": "aerobic"},
            "Frequência e intensidade não foram aumentadas ao mesmo tempo.",
        )

    distance_caps = [
        _duration_distance_cap(
            min(
                slot.max_duration_minutes,
                preferences.max_session_duration_minutes or slot.max_duration_minutes,
            ),
            context.target_pace_seconds_per_100m,
            pool,
            ruleset.rules.max_session_distance_m,
        )
        for slot in selected
    ]
    distances = _allocate_distances(
        target_volume,
        distance_caps,
        pool,
        ruleset.rules.min_session_distance_m,
    )
    allocated_volume = sum(distances)
    if allocated_volume < target_volume:
        decide(
            "DURATION_LIMIT_APPLIED",
            "RULE-DURATION-001",
            tuple(f"availability:{slot.date.isoformat()}" for slot in selected),
            {"target_volume_m": target_volume},
            {"target_volume_m": allocated_volume},
            "O volume foi reduzido para caber na duração disponível.",
        )
        target_volume = allocated_volume

    sessions: list[GeneratedSession] = []
    for slot, session_type, distance_m in zip(selected, session_types, distances, strict=True):
        max_duration = min(
            slot.max_duration_minutes,
            preferences.max_session_duration_minutes or slot.max_duration_minutes,
        )
        workout = _build_workout(
            session_type,
            distance_m,
            pool,
            context.target_pace_seconds_per_100m,
            slot.date,
        )
        validation = validate_workout(workout)
        if not validation.valid or validation.totals.distance_m != distance_m:
            raise DomainError("PLANNING_INVALID_OUTPUT", "The generated workout is invalid.")
        sessions.append(
            GeneratedSession(
                date=slot.date,
                start_local_time=slot.start_local_time,
                session_type=session_type,
                distance_m=distance_m,
                max_duration_minutes=max_duration,
                hard=session_type == "threshold_css",
                workout=workout.model_dump(mode="json", exclude_none=True),
            )
        )

    hard_sessions = [item for item in sessions if item.hard]
    hard_spacing_hours = [
        (current.date - previous.date).days * 24 for previous, current in pairwise(hard_sessions)
    ]
    if any(
        spacing < ruleset.rules.min_hours_between_hard_sessions for spacing in hard_spacing_hours
    ):
        raise DomainError(
            "PLANNING_INVALID_OUTPUT",
            "Generated hard sessions violate the configured recovery spacing.",
        )
    decide(
        "HARD_SESSION_SPACING_VERIFIED",
        "RULE-HARD-SPACING-001",
        tuple(f"session:{item.date.isoformat()}" for item in hard_sessions),
        {"required_hours": ruleset.rules.min_hours_between_hard_sessions},
        cast(
            JsonObject,
            {"observed_hours": hard_spacing_hours, "hard_sessions": len(hard_sessions)},
        ),
        "A distância entre sessões intensas respeita a recuperação mínima configurada.",
    )
    existing_dates = [item.scheduled_date.isoformat() for item in context.existing_sessions]
    generated_dates = [item.date.isoformat() for item in sessions]
    if existing_dates and existing_dates != generated_dates:
        decide(
            "RESCHEDULE_PROPOSED",
            "RULE-RESCHEDULE-001",
            tuple(f"workout:{item.workout_id}" for item in context.existing_sessions),
            cast(JsonObject, {"session_dates": existing_dates}),
            cast(JsonObject, {"session_dates": generated_dates}),
            "A distribuição proposta difere da agenda atual e permanece sem aplicação automática.",
        )

    decide(
        "WEEK_DISTRIBUTED",
        "RULE-SESSION-DISTRIBUTION-001",
        tuple(f"availability:{slot.date.isoformat()}" for slot in selected),
        {"existing_sessions": len(context.existing_sessions)},
        {"session_dates": [item.date.isoformat() for item in sessions]},
        "As sessões foram espalhadas nas janelas disponíveis e mantêm uma sessão técnica.",
    )
    raw_output: dict[str, object] = {
        "schema_version": "1.0",
        "week_start": context.week_start.isoformat(),
        "week_end": (context.week_start + timedelta(days=6)).isoformat(),
        "phase": phase,
        "target_volume_m": target_volume,
        "sessions": [item.model_dump(mode="json") for item in sessions],
        "decisions": [item.model_dump(mode="json") for item in decisions],
        "warnings": warnings,
        "ruleset_version": ruleset.version,
        "ruleset_hash": ruleset.content_hash,
    }
    return GeneratedWeek(
        week_start=context.week_start,
        week_end=context.week_start + timedelta(days=6),
        phase=phase,
        target_volume_m=target_volume,
        sessions=tuple(sessions),
        decisions=tuple(decisions),
        warnings=tuple(warnings),
        ruleset_version=ruleset.version,
        ruleset_hash=ruleset.content_hash,
        output_hash=canonical_json_hash(raw_output),
    )


def _spread_slots(slots: list[AvailabilitySnapshot], count: int) -> list[AvailabilitySnapshot]:
    if count >= len(slots):
        return slots
    if count == 1:
        return [slots[0]]
    indices = [round(index * (len(slots) - 1) / (count - 1)) for index in range(count)]
    return [slots[index] for index in indices]


def _round_pool(value: float, pool: int) -> int:
    return max(pool, int(value // pool) * pool)


def _duration_distance_cap(
    minutes: int,
    pace_seconds_per_100m: float,
    pool: int,
    configured_max: int,
) -> int:
    usable_seconds = minutes * 60 * 0.85
    estimated = usable_seconds / pace_seconds_per_100m * 100
    return min(configured_max, _round_pool(estimated, pool))


def _allocate_distances(
    target: int,
    caps: list[int],
    pool: int,
    configured_min: int,
) -> list[int]:
    count = len(caps)
    minimum = _round_pool(configured_min, pool)
    distances = [min(cap, max(minimum, _round_pool(target / count, pool))) for cap in caps]
    while sum(distances) + pool <= target:
        changed = False
        for index, cap in enumerate(caps):
            if distances[index] + pool <= cap and sum(distances) + pool <= target:
                distances[index] += pool
                changed = True
        if not changed:
            break
    while sum(distances) > target and any(value > minimum for value in distances):
        index = max(range(count), key=distances.__getitem__)
        if distances[index] > minimum:
            distances[index] -= pool
        else:
            break
    return distances


def _session_types(
    count: int,
    *,
    pain_block: bool,
    high_fatigue: bool,
    avoid_high_intensity: bool,
    focus: str,
) -> list[Literal["technique", "aerobic_endurance", "threshold_css", "recovery"]]:
    if pain_block or high_fatigue:
        base: list[Literal["technique", "aerobic_endurance", "threshold_css", "recovery"]] = [
            "technique",
            "recovery",
            "aerobic_endurance",
        ]
    elif focus == "TECHNIQUE":
        base = ["technique", "aerobic_endurance", "technique"]
    elif focus == "ENDURANCE":
        base = ["technique", "aerobic_endurance", "aerobic_endurance"]
    elif focus == "GOAL_PACE" and not avoid_high_intensity:
        base = ["technique", "aerobic_endurance", "threshold_css"]
    else:
        base = ["technique", "aerobic_endurance", "threshold_css"]
    if avoid_high_intensity:
        base = ["aerobic_endurance" if item == "threshold_css" else item for item in base]
    while len(base) < count:
        base.append("recovery" if len(base) % 2 else "aerobic_endurance")
    return base[:count]


def _build_workout(
    session_type: Literal["technique", "aerobic_endurance", "threshold_css", "recovery"],
    distance_m: int,
    pool: int,
    target_pace: float,
    session_date: date,
) -> CanonicalWorkout:
    warmup = _round_pool(distance_m * 0.2, pool)
    cooldown = _round_pool(distance_m * 0.1, pool)
    if warmup + cooldown >= distance_m:
        warmup = pool
        cooldown = pool
    main = distance_m - warmup - cooldown
    purpose = cast(
        Literal["TECHNIQUE", "ENDURANCE", "THRESHOLD", "RECOVERY"],
        {
            "technique": "TECHNIQUE",
            "aerobic_endurance": "ENDURANCE",
            "threshold_css": "THRESHOLD",
            "recovery": "RECOVERY",
        }[session_type],
    )
    pace_offsets = {
        "technique": (25, 45),
        "aerobic_endurance": (15, 30),
        "threshold_css": (-3, 8),
        "recovery": (35, 55),
    }[session_type]
    main_target = PaceTarget(
        min_seconds_per_100m=max(30, target_pace + pace_offsets[0]),
        max_seconds_per_100m=max(31, target_pace + pace_offsets[1]),
    )
    easy_target = PaceTarget(
        min_seconds_per_100m=target_pace + 30,
        max_seconds_per_100m=target_pace + 55,
    )
    nodes = (
        StepNode(
            id="warmup",
            label="Aquecimento",
            step_role="WARMUP",
            end_condition=DistanceEnd(meters=warmup),
            target=easy_target,
            stroke=StandardStroke(type="freestyle"),
            intensity="EASY",
        ),
        StepNode(
            id="main",
            label={
                "technique": "Técnica controlada",
                "aerobic_endurance": "Resistência aeróbica",
                "threshold_css": "Ritmo controlado próximo da meta",
                "recovery": "Recuperação ativa",
            }[session_type],
            step_role="DRILL" if session_type == "technique" else "WORK",
            end_condition=DistanceEnd(meters=main),
            target=main_target,
            stroke=StandardStroke(type="freestyle"),
            intensity="THRESHOLD" if session_type == "threshold_css" else "MODERATE",
            instructions=(
                "Pare e procure orientação qualificada se houver dor relevante."
                if session_type == "recovery"
                else "Mantenha execução controlada; não transforme em esforço máximo."
            ),
        ),
        StepNode(
            id="cooldown",
            label="Soltura",
            step_role="COOLDOWN",
            end_condition=DistanceEnd(meters=cooldown),
            target=easy_target,
            stroke=StandardStroke(type="choice"),
            intensity="EASY",
        ),
    )
    return CanonicalWorkout(
        title=f"{session_type.replace('_', ' ').title()} · {distance_m} m",
        description=f"Proposta determinística para {session_date.isoformat()}.",
        pool_length_m=pool,
        purpose=purpose,
        tags=("planned-week", session_type),
        nodes=nodes,
    )
