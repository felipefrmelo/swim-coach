"""Versioned medium-term training cycles and adaptation reviews."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, datetime, time
from enum import StrEnum
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from swim_coach.domain.identity.entities import utc_now
from swim_coach.domain.planning.entities import canonical_json_hash
from swim_coach.domain.shared.errors import DomainError, DomainValidationError
from swim_coach.domain.shared.types import JsonObject
from swim_coach.domain.shared.value_objects import EntityId, UserId
from swim_coach.domain.workouts import CanonicalWorkout


class PlanStatus(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PlanDecision(StrEnum):
    PROGRESS = "PROGRESS"
    HOLD = "HOLD"
    REGRESS = "REGRESS"
    RECOVERY = "RECOVERY"
    RETEST = "RETEST"
    RESCHEDULE = "RESCHEDULE"
    PAUSE = "PAUSE"


class EvidenceConfidence(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class PlanDetailLevel(StrEnum):
    DETAILED = "DETAILED"
    OUTLINE = "OUTLINE"
    STRATEGIC = "STRATEGIC"


class PrescriptionSource(StrEnum):
    COACH_DEFINED = "COACH_DEFINED"
    LEGACY_RULESET = "LEGACY_RULESET"


class PlanRevisionKind(StrEnum):
    CREATION = "CREATION"
    ADAPTATION = "ADAPTATION"
    MATERIALIZATION = "MATERIALIZATION"
    LEGACY = "LEGACY"


class PlanSessionState(StrEnum):
    PLANNED = "PLANNED"
    MATERIALIZED = "MATERIALIZED"
    COMPLETED = "COMPLETED"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"
    SUPERSEDED = "SUPERSEDED"


class NoteScope(StrEnum):
    PLAN = "PLAN"
    WEEK = "WEEK"
    SESSION = "SESSION"
    ACTIVITY = "ACTIVITY"


class NoteCategory(StrEnum):
    PERFORMANCE = "PERFORMANCE"
    TECHNIQUE = "TECHNIQUE"
    PAIN = "PAIN"
    RECOVERY = "RECOVERY"
    SCHEDULE = "SCHEDULE"
    DECISION = "DECISION"
    DATA_QUALITY = "DATA_QUALITY"


class NoteAuthor(StrEnum):
    ATHLETE = "ATHLETE"
    COACH = "COACH"
    SYSTEM = "SYSTEM"


class NoteImportance(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class PlanDocumentModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PlanPhase(PlanDocumentModel):
    name: str = Field(min_length=1, max_length=120)
    start_week: int = Field(ge=1, le=52)
    end_week: int = Field(ge=1, le=52)
    focus: str = Field(min_length=1, max_length=500)
    objectives: tuple[str, ...] = ()
    success_criteria: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_range(self) -> PlanPhase:
        if self.end_week < self.start_week:
            raise ValueError("phase end_week must not precede start_week")
        return self


class PlanSessionIntent(PlanDocumentModel):
    session_intent_id: str | None = None
    session_number: int = Field(ge=1, le=14)
    purpose: Literal[
        "TECHNIQUE",
        "BASE",
        "ENDURANCE",
        "THRESHOLD",
        "SPEED",
        "RECOVERY",
        "TEST",
        "MIXED",
        "technique",
        "aerobic_endurance",
        "threshold_css",
        "recovery",
        "test",
    ]
    objective: str | None = Field(default=None, max_length=1_000)
    coach_rationale: str | None = Field(default=None, max_length=2_000)
    coach_notes: str | None = Field(default=None, max_length=2_000)
    target_distance_m: int | None = Field(default=None, ge=1, le=50_000)
    planned_duration_minutes: int | None = Field(default=None, ge=1, le=240)
    max_duration_minutes: int | None = Field(default=None, ge=1, le=240)
    intensity: str | None = Field(default=None, min_length=1, max_length=80)
    scheduled_date: date | None = None
    scheduled_start_time: time | None = None
    pool_id: str | None = None
    key_set: str | None = Field(default=None, max_length=1_000)
    workout: CanonicalWorkout | None = None

    @model_validator(mode="after")
    def validate_identity(self) -> PlanSessionIntent:
        if self.session_intent_id is not None:
            try:
                EntityId.parse(self.session_intent_id)
            except ValueError as exc:
                raise ValueError("session_intent_id must be a UUID") from exc
        if self.pool_id is not None:
            try:
                EntityId.parse(self.pool_id)
            except ValueError as exc:
                raise ValueError("pool_id must be a UUID") from exc
        return self


class PlanWeek(PlanDocumentModel):
    week_number: int = Field(ge=1, le=52)
    focus: str = Field(min_length=1, max_length=500)
    detail_level: PlanDetailLevel
    coach_rationale: str | None = Field(default=None, max_length=2_000)
    target_distance_min_m: int | None = Field(default=None, ge=0, le=100_000)
    target_distance_max_m: int | None = Field(default=None, ge=0, le=100_000)
    target_duration_min_minutes: int | None = Field(default=None, ge=0, le=10_000)
    target_duration_max_minutes: int | None = Field(default=None, ge=0, le=10_000)
    session_count: int | None = Field(default=None, ge=0, le=14)
    load_target: str | None = Field(default=None, max_length=120)
    success_criteria: tuple[str, ...] = ()
    sessions: tuple[PlanSessionIntent, ...] = ()

    @model_validator(mode="after")
    def validate_targets(self) -> PlanWeek:
        if (
            self.target_distance_min_m is not None
            and self.target_distance_max_m is not None
            and self.target_distance_min_m > self.target_distance_max_m
        ):
            raise ValueError("week distance range is invalid")
        if (
            self.target_duration_min_minutes is not None
            and self.target_duration_max_minutes is not None
            and self.target_duration_min_minutes > self.target_duration_max_minutes
        ):
            raise ValueError("week duration range is invalid")
        if (
            self.session_count is not None
            and self.sessions
            and len(self.sessions) != self.session_count
        ):
            raise ValueError("session_count must match the supplied sessions")
        return self


class TrainingPlanDocument(PlanDocumentModel):
    schema_version: Literal["1.0", "2.0"] = "2.0"
    goal_id: str | None = None
    title: str | None = Field(default=None, max_length=160)
    start_date: date | None = None
    timezone: str | None = Field(default=None, min_length=1, max_length=100)
    prescription_source: PrescriptionSource | None = None
    strategy_summary: str = Field(min_length=1, max_length=4_000)
    review_frequency: str | None = Field(default=None, max_length=120)
    duration_weeks: int = Field(ge=4, le=16)
    baseline_snapshot: JsonObject = Field(default_factory=dict)
    baseline_confidence: EvidenceConfidence = EvidenceConfidence.LOW
    phases: tuple[PlanPhase, ...] = ()
    weeks: tuple[PlanWeek, ...]
    ruleset_version: str | None = Field(default=None, min_length=1, max_length=40)
    ruleset_hash: str | None = Field(default=None, min_length=64, max_length=64)

    @model_validator(mode="after")
    def validate_structure(self) -> TrainingPlanDocument:
        week_numbers = [item.week_number for item in self.weeks]
        if week_numbers != list(range(1, self.duration_weeks + 1)):
            raise ValueError("plan weeks must be contiguous and cover the duration")
        if self.phases:
            if self.phases[0].start_week != 1 or self.phases[-1].end_week != self.duration_weeks:
                raise ValueError("plan phases must cover the full duration")
            previous_end = 0
            for phase in self.phases:
                if phase.start_week != previous_end + 1:
                    raise ValueError("plan phases must be contiguous")
                previous_end = phase.end_week
        session_ids = [
            item.session_intent_id
            for week in self.weeks
            for item in week.sessions
            if item.session_intent_id is not None
        ]
        if len(session_ids) != len(set(session_ids)):
            raise ValueError("session intent IDs must be unique within a revision")
        if self.schema_version == "2.0":
            if self.prescription_source is not PrescriptionSource.COACH_DEFINED:
                raise ValueError("new plan definitions must be coach-defined")
            if self.goal_id is None or self.title is None or self.start_date is None:
                raise ValueError("coach-defined plans require goal_id, title and start_date")
            try:
                EntityId.parse(self.goal_id)
            except ValueError as exc:
                raise ValueError("goal_id must be a UUID") from exc
            if self.ruleset_version is not None or self.ruleset_hash is not None:
                raise ValueError("coach-defined plans cannot include generation ruleset metadata")
            for week in self.weeks:
                if week.detail_level is PlanDetailLevel.DETAILED and not week.sessions:
                    raise ValueError("a detailed week requires coach-authored sessions")
                if week.detail_level is not PlanDetailLevel.DETAILED and any(
                    session.workout is not None for session in week.sessions
                ):
                    raise ValueError(
                        "outline and strategic sessions cannot contain a materialized workout"
                    )
                session_numbers = [item.session_number for item in week.sessions]
                if len(session_numbers) != len(set(session_numbers)):
                    raise ValueError("session numbers must be unique within a week")
                for session in week.sessions:
                    if session.purpose != session.purpose.upper():
                        raise ValueError("coach-defined session purposes must use canonical values")
                    if session.max_duration_minutes is not None:
                        raise ValueError(
                            "coach-defined sessions use planned_duration_minutes, "
                            "not legacy max_duration_minutes"
                        )
                    if week.detail_level is PlanDetailLevel.DETAILED and (
                        session.scheduled_date is None
                        or session.scheduled_start_time is None
                        or session.planned_duration_minutes is None
                        or session.target_distance_m is None
                        or session.workout is None
                    ):
                        raise ValueError(
                            "a detailed session requires schedule, duration, distance and workout"
                        )
        elif self.prescription_source is not PrescriptionSource.LEGACY_RULESET:
            object.__setattr__(self, "prescription_source", PrescriptionSource.LEGACY_RULESET)
        return self

    @property
    def content_hash(self) -> str:
        if self.schema_version == "1.0":
            return canonical_json_hash(self._legacy_hash_payload())
        return canonical_json_hash(self.as_json())

    def as_json(self) -> JsonObject:
        """Serialize a plan while keeping generation metadata exclusive to legacy documents."""

        excluded = {"ruleset_version", "ruleset_hash"} if self.schema_version == "2.0" else set()
        return cast(JsonObject, self.model_dump(mode="json", exclude=excluded))

    def _legacy_hash_payload(self) -> JsonObject:
        return cast(
            JsonObject,
            {
                "schema_version": "1.0",
                "strategy_summary": self.strategy_summary,
                "duration_weeks": self.duration_weeks,
                "baseline_snapshot": self.baseline_snapshot,
                "baseline_confidence": self.baseline_confidence.value,
                "phases": [item.model_dump(mode="json") for item in self.phases],
                "weeks": [
                    {
                        "week_number": week.week_number,
                        "focus": week.focus,
                        "detail_level": week.detail_level.value,
                        "target_distance_min_m": week.target_distance_min_m,
                        "target_distance_max_m": week.target_distance_max_m,
                        "target_duration_min_minutes": week.target_duration_min_minutes,
                        "target_duration_max_minutes": week.target_duration_max_minutes,
                        "session_count": week.session_count,
                        "load_target": week.load_target,
                        "success_criteria": list(week.success_criteria),
                        "sessions": [
                            {
                                "session_intent_id": session.session_intent_id,
                                "session_number": session.session_number,
                                "purpose": session.purpose,
                                "target_distance_m": session.target_distance_m,
                                "max_duration_minutes": session.max_duration_minutes,
                                "intensity": session.intensity,
                                "scheduled_date": (
                                    session.scheduled_date.isoformat()
                                    if session.scheduled_date
                                    else None
                                ),
                                "key_set": session.key_set,
                                "workout": (
                                    session.workout.model_dump(mode="json")
                                    if session.workout is not None
                                    else None
                                ),
                            }
                            for session in week.sessions
                        ],
                    }
                    for week in self.weeks
                ],
                "ruleset_version": self.ruleset_version,
                "ruleset_hash": self.ruleset_hash,
            },
        )


class TrainingPlanRevisionDefinition(PlanDocumentModel):
    schema_version: Literal["1.0"] = "1.0"
    kind: Literal["ADAPTATION", "MATERIALIZATION"]
    review_id: str | None = None
    decision: PlanDecision | None = None
    rationale: str = Field(min_length=1, max_length=2_000)
    definition: TrainingPlanDocument

    @model_validator(mode="after")
    def validate_revision_intent(self) -> TrainingPlanRevisionDefinition:
        if self.definition.schema_version != "2.0":
            raise ValueError("revision definitions must contain a coach-defined schema 2.0 plan")
        if self.kind == "ADAPTATION":
            if self.review_id is None or self.decision is None:
                raise ValueError("adaptive revisions require review_id and decision")
            try:
                EntityId.parse(self.review_id)
            except ValueError as exc:
                raise ValueError("review_id must be a UUID") from exc
        elif self.review_id is not None or self.decision is not None:
            raise ValueError(
                "materialization revisions cannot include review or adaptation decision"
            )
        return self


@dataclass(slots=True)
class TrainingPlan:
    id: EntityId
    user_id: UserId
    goal_id: EntityId
    title: str
    start_date: date
    end_date: date
    duration_weeks: int
    prescription_source: PrescriptionSource = PrescriptionSource.COACH_DEFINED
    status: PlanStatus = PlanStatus.DRAFT
    adaptation_mode: str = "MANUAL_APPROVAL"
    current_revision: int = 0
    current_revision_id: EntityId | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    version: int = 1

    def __post_init__(self) -> None:
        self.title = self.title.strip()
        if not self.title or self.duration_weeks < 4 or self.duration_weeks > 16:
            raise DomainValidationError("training plan title or duration is invalid")
        if self.start_date.weekday() != 0:
            raise DomainValidationError("training plan start_date must be a Monday")
        expected_end = self.start_date.fromordinal(
            self.start_date.toordinal() + self.duration_weeks * 7 - 1
        )
        if self.end_date != expected_end:
            raise DomainValidationError("training plan end_date does not match its duration")
        if self.current_revision < 0 or self.version < 1:
            raise DomainValidationError("training plan version is invalid")
        if (self.current_revision == 0) != (self.current_revision_id is None):
            raise DomainValidationError("training plan current revision identity is inconsistent")
        if self.adaptation_mode != "MANUAL_APPROVAL":
            raise DomainValidationError("unsupported training plan adaptation mode")

    def apply_revision(self, revision: TrainingPlanRevision, now: datetime) -> None:
        if revision.plan_id != self.id or revision.revision_number != self.current_revision + 1:
            raise DomainError("PLAN_REVISION_CONFLICT", "The plan revision is stale.")
        self.current_revision = revision.revision_number
        self.current_revision_id = revision.id
        if self.status is PlanStatus.DRAFT:
            self.status = PlanStatus.ACTIVE
        self.updated_at = now
        self.version += 1

    def set_status(self, status: PlanStatus, now: datetime) -> None:
        allowed = {
            PlanStatus.ACTIVE: {PlanStatus.PAUSED, PlanStatus.COMPLETED, PlanStatus.CANCELLED},
            PlanStatus.PAUSED: {PlanStatus.ACTIVE, PlanStatus.CANCELLED},
            PlanStatus.DRAFT: {PlanStatus.CANCELLED},
        }
        if status not in allowed.get(self.status, set()):
            raise DomainError("PLAN_STATE_CONFLICT", "The plan status transition is invalid.")
        self.status = status
        self.updated_at = now
        self.version += 1


@dataclass(frozen=True, slots=True)
class TrainingPlanRevision:
    id: EntityId
    plan_id: EntityId
    revision_number: int
    document: TrainingPlanDocument
    content_hash: str
    reason: str
    revision_kind: PlanRevisionKind = PlanRevisionKind.CREATION
    decision: PlanDecision | None = None
    previous_revision_id: EntityId | None = None
    effective_from: date | None = None
    evidence: JsonObject = field(default_factory=dict)
    diff: JsonObject = field(default_factory=dict)
    proposal_id: EntityId | None = None
    created_by: str = "system"
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if self.revision_number < 1 or not self.reason.strip() or not self.created_by.strip():
            raise DomainValidationError("training plan revision is incomplete")
        if self.content_hash != self.document.content_hash:
            raise DomainValidationError("training plan revision hash does not match")
        if self.revision_number == 1 and self.previous_revision_id is not None:
            raise DomainValidationError("the first plan revision cannot have a predecessor")
        if self.revision_number > 1 and self.previous_revision_id is None:
            raise DomainValidationError("later plan revisions require a predecessor")


@dataclass(slots=True)
class PlanSessionBinding:
    id: EntityId
    user_id: UserId
    plan_id: EntityId
    session_intent_id: EntityId
    week_number: int
    state: PlanSessionState = PlanSessionState.PLANNED
    workout_id: EntityId | None = None
    materialized_plan_revision: int | None = None
    materialized_workout_hash: str | None = None
    locked_reason: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    version: int = 1

    def __post_init__(self) -> None:
        if self.week_number < 1 or self.version < 1:
            raise DomainValidationError("plan session binding is invalid")
        if self.materialized_workout_hash is not None and len(self.materialized_workout_hash) != 64:
            raise DomainValidationError("materialized workout hash is invalid")

    @property
    def locked(self) -> bool:
        return self.locked_reason is not None or self.state in {
            PlanSessionState.COMPLETED,
            PlanSessionState.SKIPPED,
            PlanSessionState.CANCELLED,
        }


@dataclass(frozen=True, slots=True)
class PlanReview:
    id: EntityId
    user_id: UserId
    plan_id: EntityId
    plan_revision: int
    week_number: int
    evidence_snapshot: JsonObject
    evidence_hash: str
    confidence_cap: EvidenceConfidence
    eligible: bool
    eligibility_reason: str
    decision: PlanDecision | None = None
    rationale: str | None = None
    recommendation: JsonObject = field(default_factory=dict)
    proposal_id: EntityId | None = None
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if self.plan_revision < 1 or self.week_number < 1:
            raise DomainValidationError("plan review target is invalid")
        if self.evidence_hash != canonical_json_hash(self.evidence_snapshot):
            raise DomainValidationError("plan review evidence hash does not match")
        if self.decision is None and (self.rationale is not None or self.proposal_id is not None):
            raise DomainValidationError("review recommendation requires a decision")

    def with_recommendation(
        self,
        *,
        decision: PlanDecision,
        rationale: str,
        recommendation: JsonObject,
        proposal_id: EntityId,
    ) -> PlanReview:
        if self.decision is not None:
            raise DomainError(
                "PLAN_REVIEW_ALREADY_PROPOSED",
                "This evidence review already has a revision proposal.",
            )
        normalized_rationale = rationale.strip()
        if not normalized_rationale:
            raise DomainValidationError("review rationale is required")
        return replace(
            self,
            decision=decision,
            rationale=normalized_rationale,
            recommendation=recommendation,
            proposal_id=proposal_id,
        )


@dataclass(frozen=True, slots=True)
class PlanNote:
    id: EntityId
    user_id: UserId
    plan_id: EntityId
    scope_type: NoteScope
    scope_ref: str
    category: NoteCategory
    author_type: NoteAuthor
    text: str
    importance: NoteImportance = NoteImportance.MEDIUM
    affects_adaptation: bool = True
    valid_from: date | None = None
    valid_until: date | None = None
    evidence_activity_refs: tuple[str, ...] = ()
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not self.scope_ref.strip() or not self.text.strip():
            raise DomainValidationError("plan note is incomplete")
        if len(self.text) > 2_000:
            raise DomainValidationError("plan note is too long")
        if self.valid_until is not None and self.valid_from is not None:
            if self.valid_until < self.valid_from:
                raise DomainValidationError("plan note validity is invalid")


def plan_document_diff(
    before: TrainingPlanDocument | None, after: TrainingPlanDocument
) -> JsonObject:
    """Return a compact deterministic revision diff suitable for review and hashing."""

    if before is None:
        return cast(
            JsonObject,
            {
                "type": "CREATE",
                "weeks_added": list(range(1, after.duration_weeks + 1)),
                "session_count_after": sum(len(item.sessions) for item in after.weeks),
            },
        )
    before_weeks = {item.week_number: item for item in before.weeks}
    changed_weeks: list[JsonObject] = []
    for week in after.weeks:
        previous = before_weeks.get(week.week_number)
        if previous == week:
            continue
        changed_weeks.append(
            {
                "week_number": week.week_number,
                "before": previous.model_dump(mode="json") if previous else None,
                "after": week.model_dump(mode="json"),
            }
        )
    removed = sorted(set(before_weeks) - {item.week_number for item in after.weeks})
    return cast(
        JsonObject,
        {
            "type": "REVISION",
            "changed_weeks": changed_weeks,
            "removed_weeks": removed,
            "strategy_changed": before.strategy_summary != after.strategy_summary,
            "review_frequency_changed": before.review_frequency != after.review_frequency,
            "phases_changed": before.phases != after.phases,
            "session_count_before": sum(len(item.sessions) for item in before.weeks),
            "session_count_after": sum(len(item.sessions) for item in after.weeks),
        },
    )
