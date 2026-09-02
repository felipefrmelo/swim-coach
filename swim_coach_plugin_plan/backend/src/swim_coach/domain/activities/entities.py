"""Versioned normalized activity records with explicit units and data quality."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from swim_coach.domain.identity.entities import utc_now
from swim_coach.domain.shared.errors import DomainValidationError
from swim_coach.domain.shared.types import JsonObject
from swim_coach.domain.shared.value_objects import EntityId, UserId


def _sha256(value: str, label: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise DomainValidationError(f"{label} must be a lowercase SHA-256 digest")


def _non_negative(value: Decimal | None, label: str) -> None:
    if value is not None and value < 0:
        raise DomainValidationError(f"{label} cannot be negative")


class DataQuality(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    POOR = "poor"


class ProvenanceSource(StrEnum):
    GARMIN = "garmin"
    DERIVED = "derived"
    PLANNED_WORKOUT = "planned_workout"
    INFERRED = "inferred"


class IntervalType(StrEnum):
    SWIM = "swim"
    REST = "rest"
    DRILL = "drill"
    UNKNOWN = "unknown"


class PlannedRole(StrEnum):
    WARMUP = "warmup"
    WORK = "work"
    RECOVERY = "recovery"
    REST = "rest"
    COOLDOWN = "cooldown"
    DRILL = "drill"
    OTHER = "other"


class LengthType(StrEnum):
    ACTIVE = "active"
    IDLE = "idle"
    UNKNOWN = "unknown"


def _enum_value(value: StrEnum | str, label: str, allowed: frozenset[str]) -> str:
    normalized = str(value).strip().lower()
    if normalized not in allowed:
        raise DomainValidationError(f"{label} is invalid")
    return normalized


def _synchronized_alias(
    instance: object,
    *,
    canonical_name: str,
    legacy_name: str,
) -> None:
    canonical = getattr(instance, canonical_name)
    legacy = getattr(instance, legacy_name)
    if canonical is None and legacy is not None:
        object.__setattr__(instance, canonical_name, legacy)
    elif legacy is None and canonical is not None:
        object.__setattr__(instance, legacy_name, canonical)
    elif canonical is not None and legacy is not None and canonical != legacy:
        raise DomainValidationError(
            f"{canonical_name} and its legacy alias {legacy_name} must agree"
        )


@dataclass(frozen=True, slots=True)
class FileArtifact:
    id: EntityId
    user_id: UserId
    activity_id: EntityId
    provider: str
    artifact_type: str
    storage_key: str
    content_type: str
    size_bytes: int
    checksum: str
    source_external_id_hash: str
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (
                self.provider,
                self.artifact_type,
                self.storage_key,
                self.content_type,
                self.source_external_id_hash,
            )
        ):
            raise DomainValidationError("file artifact identity fields are required")
        if self.storage_key.startswith("/") or ".." in self.storage_key.split("/"):
            raise DomainValidationError("file artifact storage key must be relative and safe")
        if self.size_bytes <= 0:
            raise DomainValidationError("file artifact cannot be empty")
        _sha256(self.checksum, "file artifact checksum")
        _sha256(self.source_external_id_hash, "source external id hash")


@dataclass(frozen=True, slots=True)
class ActivityLap:
    id: EntityId
    normalization_id: EntityId
    lap_index: int
    start_offset_seconds: Decimal
    elapsed_seconds: Decimal
    timer_seconds: Decimal
    distance_m: int
    avg_hr_bpm: int | None = None
    max_hr_bpm: int | None = None
    stroke_type: str | None = None
    moving_seconds: Decimal | None = None
    swim_seconds: Decimal | None = None
    rest_seconds: Decimal | None = None
    stationary_seconds: Decimal | None = None
    garmin_reported_speed_m_per_s: Decimal | None = None
    pace_from_garmin_reported_speed_seconds_per_100m: Decimal | None = None
    moving_pace_seconds_per_100m: Decimal | None = None
    swim_pace_seconds_per_100m: Decimal | None = None
    timer_pace_seconds_per_100m: Decimal | None = None
    elapsed_pace_seconds_per_100m: Decimal | None = None
    detected_stroke: str | None = None
    planned_stroke: str | None = None
    provenance: JsonObject = field(default_factory=dict)
    quality_warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.lap_index < 0 or self.distance_m < 0:
            raise DomainValidationError("lap index and distance cannot be negative")
        _non_negative(self.start_offset_seconds, "lap start offset")
        for value, label in (
            (self.elapsed_seconds, "lap elapsed duration"),
            (self.timer_seconds, "lap timer duration"),
            (self.moving_seconds, "lap moving duration"),
            (self.swim_seconds, "lap swim duration"),
            (self.rest_seconds, "lap rest duration"),
            (self.stationary_seconds, "lap stationary duration"),
            (self.garmin_reported_speed_m_per_s, "lap Garmin speed"),
            (
                self.pace_from_garmin_reported_speed_seconds_per_100m,
                "lap pace from Garmin-reported speed",
            ),
            (self.moving_pace_seconds_per_100m, "lap moving pace"),
            (self.swim_pace_seconds_per_100m, "lap swim pace"),
            (self.timer_pace_seconds_per_100m, "lap timer pace"),
            (self.elapsed_pace_seconds_per_100m, "lap elapsed pace"),
        ):
            _non_negative(value, label)
        _synchronized_alias(self, canonical_name="detected_stroke", legacy_name="stroke_type")

    @property
    def elapsed_duration_s(self) -> Decimal:
        return self.elapsed_seconds

    @property
    def timer_duration_s(self) -> Decimal:
        return self.timer_seconds

    @property
    def moving_duration_s(self) -> Decimal | None:
        return self.moving_seconds

    @property
    def swim_duration_s(self) -> Decimal | None:
        return self.swim_seconds

    @property
    def rest_duration_s(self) -> Decimal | None:
        return self.rest_seconds

    @property
    def stationary_duration_s(self) -> Decimal | None:
        return self.stationary_seconds


@dataclass(frozen=True, slots=True)
class ActivityInterval:
    id: EntityId
    normalization_id: EntityId
    interval_index: int
    interval_type: str
    start_offset_seconds: Decimal
    duration_seconds: Decimal
    rest_seconds: Decimal
    distance_m: int
    pace_seconds_per_100m: Decimal | None = None
    avg_hr_bpm: int | None = None
    max_hr_bpm: int | None = None
    stroke_type: str | None = None
    stroke_count: int | None = None
    stroke_rate: Decimal | None = None
    swolf: Decimal | None = None
    source: JsonObject = field(default_factory=dict)
    elapsed_seconds: Decimal | None = None
    timer_seconds: Decimal | None = None
    moving_seconds: Decimal | None = None
    swim_seconds: Decimal | None = None
    stationary_seconds: Decimal | None = None
    garmin_reported_speed_m_per_s: Decimal | None = None
    pace_from_garmin_reported_speed_seconds_per_100m: Decimal | None = None
    moving_pace_seconds_per_100m: Decimal | None = None
    swim_pace_seconds_per_100m: Decimal | None = None
    timer_pace_seconds_per_100m: Decimal | None = None
    elapsed_pace_seconds_per_100m: Decimal | None = None
    planned_role: str | None = None
    detected_stroke: str | None = None
    planned_stroke: str | None = None
    provenance: JsonObject = field(default_factory=dict)
    quality_warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.interval_index < 0 or self.distance_m < 0:
            raise DomainValidationError("interval index and distance cannot be negative")
        object.__setattr__(
            self,
            "interval_type",
            _enum_value(
                self.interval_type,
                "interval type",
                frozenset({"work", *(item.value for item in IntervalType)}),
            ),
        )
        if self.planned_role is not None:
            object.__setattr__(
                self,
                "planned_role",
                _enum_value(
                    self.planned_role,
                    "planned role",
                    frozenset(item.value for item in PlannedRole),
                ),
            )
        if self.timer_seconds is not None and self.timer_seconds != self.duration_seconds:
            raise DomainValidationError("interval timer and legacy duration must agree")
        _synchronized_alias(
            self,
            canonical_name="timer_pace_seconds_per_100m",
            legacy_name="pace_seconds_per_100m",
        )
        _synchronized_alias(self, canonical_name="detected_stroke", legacy_name="stroke_type")
        for value, label in (
            (self.start_offset_seconds, "interval start offset"),
            (self.duration_seconds, "interval duration"),
            (self.rest_seconds, "interval rest"),
            (self.pace_seconds_per_100m, "interval pace"),
            (self.elapsed_seconds, "interval elapsed duration"),
            (self.timer_seconds, "interval timer duration"),
            (self.moving_seconds, "interval moving duration"),
            (self.swim_seconds, "interval swim duration"),
            (self.stationary_seconds, "interval stationary duration"),
            (self.garmin_reported_speed_m_per_s, "interval Garmin speed"),
            (
                self.pace_from_garmin_reported_speed_seconds_per_100m,
                "interval pace from Garmin-reported speed",
            ),
            (self.moving_pace_seconds_per_100m, "interval moving pace"),
            (self.swim_pace_seconds_per_100m, "interval swim pace"),
            (self.timer_pace_seconds_per_100m, "interval timer pace"),
            (self.elapsed_pace_seconds_per_100m, "interval elapsed pace"),
            (self.stroke_rate, "interval stroke rate"),
            (self.swolf, "interval SWOLF"),
        ):
            _non_negative(value, label)
        if self.stroke_count is not None and self.stroke_count < 0:
            raise DomainValidationError("interval stroke count cannot be negative")

    @property
    def elapsed_duration_s(self) -> Decimal | None:
        return self.elapsed_seconds

    @property
    def timer_duration_s(self) -> Decimal | None:
        return self.timer_seconds

    @property
    def moving_duration_s(self) -> Decimal | None:
        return self.moving_seconds

    @property
    def swim_duration_s(self) -> Decimal | None:
        return self.swim_seconds

    @property
    def rest_duration_s(self) -> Decimal:
        return self.rest_seconds

    @property
    def stationary_duration_s(self) -> Decimal | None:
        return self.stationary_seconds


@dataclass(frozen=True, slots=True)
class ActivityLength:
    id: EntityId
    normalization_id: EntityId
    interval_id: EntityId
    length_index: int
    distance_m: int
    duration_seconds: Decimal
    stroke_type: str | None = None
    stroke_count: int | None = None
    stroke_rate: Decimal | None = None
    swolf: Decimal | None = None
    avg_hr_bpm: int | None = None
    length_type: str = LengthType.ACTIVE.value
    elapsed_seconds: Decimal | None = None
    timer_seconds: Decimal | None = None
    moving_seconds: Decimal | None = None
    swim_seconds: Decimal | None = None
    rest_seconds: Decimal | None = None
    stationary_seconds: Decimal | None = None
    garmin_reported_speed_m_per_s: Decimal | None = None
    pace_from_garmin_reported_speed_seconds_per_100m: Decimal | None = None
    moving_pace_seconds_per_100m: Decimal | None = None
    swim_pace_seconds_per_100m: Decimal | None = None
    timer_pace_seconds_per_100m: Decimal | None = None
    elapsed_pace_seconds_per_100m: Decimal | None = None
    detected_stroke: str | None = None
    planned_stroke: str | None = None
    provenance: JsonObject = field(default_factory=dict)
    quality_warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.length_index < 0 or self.distance_m < 0:
            raise DomainValidationError("length index and distance cannot be negative")
        object.__setattr__(
            self,
            "length_type",
            _enum_value(
                self.length_type,
                "length type",
                frozenset(item.value for item in LengthType),
            ),
        )
        if self.length_type == LengthType.ACTIVE and self.distance_m <= 0:
            raise DomainValidationError("active length distance must be positive")
        if self.length_type == LengthType.IDLE and self.distance_m != 0:
            raise DomainValidationError("idle length distance must be zero")
        if self.timer_seconds is not None and self.timer_seconds != self.duration_seconds:
            raise DomainValidationError("length timer and legacy duration must agree")
        _synchronized_alias(self, canonical_name="detected_stroke", legacy_name="stroke_type")
        for value, label in (
            (self.duration_seconds, "length duration"),
            (self.elapsed_seconds, "length elapsed duration"),
            (self.timer_seconds, "length timer duration"),
            (self.moving_seconds, "length moving duration"),
            (self.swim_seconds, "length swim duration"),
            (self.rest_seconds, "length rest duration"),
            (self.stationary_seconds, "length stationary duration"),
            (self.garmin_reported_speed_m_per_s, "length Garmin speed"),
            (
                self.pace_from_garmin_reported_speed_seconds_per_100m,
                "length pace from Garmin-reported speed",
            ),
            (self.moving_pace_seconds_per_100m, "length moving pace"),
            (self.swim_pace_seconds_per_100m, "length swim pace"),
            (self.timer_pace_seconds_per_100m, "length timer pace"),
            (self.elapsed_pace_seconds_per_100m, "length elapsed pace"),
            (self.stroke_rate, "length stroke rate"),
            (self.swolf, "length SWOLF"),
        ):
            _non_negative(value, label)
        if self.stroke_count is not None and self.stroke_count < 0:
            raise DomainValidationError("length stroke count cannot be negative")

    @property
    def elapsed_duration_s(self) -> Decimal | None:
        return self.elapsed_seconds

    @property
    def timer_duration_s(self) -> Decimal | None:
        return self.timer_seconds

    @property
    def moving_duration_s(self) -> Decimal | None:
        return self.moving_seconds

    @property
    def swim_duration_s(self) -> Decimal | None:
        return self.swim_seconds

    @property
    def rest_duration_s(self) -> Decimal | None:
        return self.rest_seconds

    @property
    def stationary_duration_s(self) -> Decimal | None:
        return self.stationary_seconds


@dataclass(frozen=True, slots=True)
class ActivityNormalization:
    id: EntityId
    user_id: UserId
    activity_id: EntityId
    artifact_id: EntityId
    parser_version: str
    profile_version: str
    input_checksum: str
    pool_length_m: int
    distance_m: int
    elapsed_seconds: Decimal
    timer_seconds: Decimal
    moving_seconds: Decimal | None
    active_length_count: int
    completeness: Decimal
    quality: DataQuality
    warnings: tuple[str, ...] = ()
    created_at: datetime = field(default_factory=utc_now)
    swim_seconds: Decimal | None = None
    rest_seconds: Decimal | None = None
    stationary_seconds: Decimal | None = None
    garmin_reported_speed_m_per_s: Decimal | None = None
    pace_from_garmin_reported_speed_seconds_per_100m: Decimal | None = None
    moving_pace_seconds_per_100m: Decimal | None = None
    swim_pace_seconds_per_100m: Decimal | None = None
    timer_pace_seconds_per_100m: Decimal | None = None
    session_pace_seconds_per_100m: Decimal | None = None
    perceived_effort_rpe: Decimal | None = None
    feeling_score: int | None = None
    provenance: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.parser_version.strip() or not self.profile_version.strip():
            raise DomainValidationError("normalization parser and profile versions are required")
        _sha256(self.input_checksum, "normalization input checksum")
        if self.pool_length_m <= 0 or self.distance_m < 0 or self.active_length_count < 0:
            raise DomainValidationError("normalization distances and counts are invalid")
        for value, label in (
            (self.elapsed_seconds, "normalization elapsed duration"),
            (self.timer_seconds, "normalization timer duration"),
            (self.moving_seconds, "normalization moving duration"),
            (self.swim_seconds, "normalization swim duration"),
            (self.rest_seconds, "normalization rest duration"),
            (self.stationary_seconds, "normalization stationary duration"),
            (self.garmin_reported_speed_m_per_s, "normalization Garmin speed"),
            (
                self.pace_from_garmin_reported_speed_seconds_per_100m,
                "normalization pace from Garmin-reported speed",
            ),
            (self.moving_pace_seconds_per_100m, "normalization moving pace"),
            (self.swim_pace_seconds_per_100m, "normalization swim pace"),
            (self.timer_pace_seconds_per_100m, "normalization timer pace"),
            (self.session_pace_seconds_per_100m, "normalization session pace"),
        ):
            _non_negative(value, label)
        if self.perceived_effort_rpe is not None:
            rpe = self.perceived_effort_rpe
            if (
                not rpe.is_finite()
                or not Decimal(0) <= rpe <= Decimal(10)
                or rpe * Decimal(10) != (rpe * Decimal(10)).to_integral_value()
            ):
                raise DomainValidationError(
                    "normalization perceived effort RPE must be between 0 and 10 in 0.1 increments"
                )
        if self.feeling_score is not None and not 0 <= self.feeling_score <= 100:
            raise DomainValidationError("normalization feeling score must be between 0 and 100")
        if not Decimal("0") <= self.completeness <= Decimal("1"):
            raise DomainValidationError("normalization completeness must be between zero and one")

    @property
    def elapsed_duration_s(self) -> Decimal:
        return self.elapsed_seconds

    @property
    def timer_duration_s(self) -> Decimal:
        return self.timer_seconds

    @property
    def moving_duration_s(self) -> Decimal | None:
        return self.moving_seconds

    @property
    def swim_duration_s(self) -> Decimal | None:
        return self.swim_seconds

    @property
    def rest_duration_s(self) -> Decimal | None:
        return self.rest_seconds

    @property
    def stationary_duration_s(self) -> Decimal | None:
        return self.stationary_seconds


@dataclass(frozen=True, slots=True)
class NormalizedActivity:
    normalization: ActivityNormalization
    laps: tuple[ActivityLap, ...]
    intervals: tuple[ActivityInterval, ...]
    lengths: tuple[ActivityLength, ...]

    def __post_init__(self) -> None:
        normalization_id = self.normalization.id
        if any(item.normalization_id != normalization_id for item in self.laps):
            raise DomainValidationError("lap belongs to another normalization")
        if any(item.normalization_id != normalization_id for item in self.intervals):
            raise DomainValidationError("interval belongs to another normalization")
        if any(item.normalization_id != normalization_id for item in self.lengths):
            raise DomainValidationError("length belongs to another normalization")
        interval_ids = {item.id for item in self.intervals}
        if any(item.interval_id not in interval_ids for item in self.lengths):
            raise DomainValidationError("length belongs to an unknown interval")


@dataclass(frozen=True, slots=True)
class ActivityAnalysis:
    id: EntityId
    user_id: UserId
    activity_id: EntityId
    normalization_id: EntityId
    analysis_version: str
    parser_version: str
    input_checksum: str
    pool_length_m: int
    metrics: JsonObject
    flags: tuple[str, ...]
    quality: DataQuality
    summary: JsonObject
    planned_workout_id: EntityId | None = None
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not self.analysis_version.strip() or not self.parser_version.strip():
            raise DomainValidationError("analysis versions are required")
        _sha256(self.input_checksum, "analysis input checksum")
        if self.pool_length_m <= 0:
            raise DomainValidationError("analysis pool length must be positive")


@dataclass(frozen=True, slots=True)
class WorkoutExecutionMatch:
    id: EntityId
    user_id: UserId
    activity_id: EntityId
    planned_workout_id: EntityId
    method: str
    confidence: Decimal
    score_details: JsonObject
    confirmed_at: datetime | None = None
    confirmed_by: str | None = None
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if self.method not in {"automatic", "suggested", "manual"}:
            raise DomainValidationError("workout match method is invalid")
        if not Decimal("0") <= self.confidence <= Decimal("1"):
            raise DomainValidationError("workout match confidence must be between zero and one")
        if self.method == "manual" and (self.confirmed_at is None or not self.confirmed_by):
            raise DomainValidationError("manual match requires confirmation metadata")


@dataclass(slots=True)
class SessionFeedback:
    id: EntityId
    user_id: UserId
    activity_id: EntityId
    rpe: int | None
    provider: str = ""
    external_activity_id: str = ""
    technique_rating: int | None = None
    fatigue_rating: int | None = None
    enjoyment_rating: int | None = None
    feeling_score: int | None = None
    pain_present: bool = False
    pain_location: str | None = None
    pain_intensity: int | None = None
    comment: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    version: int = 1

    def __post_init__(self) -> None:
        if self.rpe is not None and not 1 <= self.rpe <= 10:
            raise DomainValidationError("RPE must be between 1 and 10")
        if self.feeling_score is not None and not 0 <= self.feeling_score <= 100:
            raise DomainValidationError("feeling score must be between 0 and 100")
        for value, label in (
            (self.technique_rating, "technique rating"),
            (self.fatigue_rating, "fatigue rating"),
            (self.enjoyment_rating, "enjoyment rating"),
        ):
            if value is not None and not 1 <= value <= 5:
                raise DomainValidationError(f"{label} must be between 1 and 5")
        if self.pain_present:
            if self.pain_intensity is None or not 1 <= self.pain_intensity <= 10:
                raise DomainValidationError("pain intensity must be between 1 and 10")
            if not self.pain_location or not self.pain_location.strip():
                raise DomainValidationError("pain location is required when pain is present")
        elif self.pain_intensity is not None or self.pain_location is not None:
            raise DomainValidationError("pain details require pain_present")
        if self.comment is not None and len(self.comment) > 2_000:
            raise DomainValidationError("feedback comment is too long")
        if self.version < 1:
            raise DomainValidationError("feedback version must be positive")

    def revise(
        self,
        *,
        rpe: int | None,
        technique_rating: int | None,
        fatigue_rating: int | None,
        enjoyment_rating: int | None,
        feeling_score: int | None,
        pain_present: bool,
        pain_location: str | None,
        pain_intensity: int | None,
        comment: str | None,
    ) -> None:
        candidate = SessionFeedback(
            id=self.id,
            user_id=self.user_id,
            activity_id=self.activity_id,
            rpe=rpe,
            provider=self.provider,
            external_activity_id=self.external_activity_id,
            technique_rating=technique_rating,
            fatigue_rating=fatigue_rating,
            enjoyment_rating=enjoyment_rating,
            feeling_score=feeling_score,
            pain_present=pain_present,
            pain_location=pain_location,
            pain_intensity=pain_intensity,
            comment=comment,
            created_at=self.created_at,
            updated_at=utc_now(),
            version=self.version + 1,
        )
        self.rpe = candidate.rpe
        self.technique_rating = candidate.technique_rating
        self.fatigue_rating = candidate.fatigue_rating
        self.enjoyment_rating = candidate.enjoyment_rating
        self.feeling_score = candidate.feeling_score
        self.pain_present = candidate.pain_present
        self.pain_location = candidate.pain_location
        self.pain_intensity = candidate.pain_intensity
        self.comment = candidate.comment
        self.updated_at = candidate.updated_at
        self.version = candidate.version


@dataclass(frozen=True, slots=True)
class WorkoutMatchCandidate:
    workout_id: EntityId
    scheduled_date: date
    distance_m: int
    estimated_seconds: Decimal
    title: str
