"""Pure, provider-neutral contextual analytics for normalized pool swims.

The functions in this module deliberately accept mappings or objects with attributes.
That keeps the analysis independent from persistence and from a particular version of
the normalized activity dataclasses.  Pace selection is always explicit: a missing
moving pace is not silently replaced by timer pace or pace derived from
Garmin-reported speed.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from enum import StrEnum
from statistics import median
from typing import Final

_ZERO: Final = Decimal(0)
_ONE: Final = Decimal(1)
_MILLISECOND: Final = Decimal("0.001")
_HUNDREDTH: Final = Decimal("0.01")
_FOUR_PLACES: Final = Decimal("0.0001")
_UNPLANNED_SET_BOUNDARY_REST_S: Final = Decimal("60")


class QualityLevel(StrEnum):
    """Strength of the evidence supporting an analysis."""

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class TrendDirection(StrEnum):
    """Direction of pace across equivalent repetitions (lower pace is faster)."""

    FASTER = "FASTER"
    STABLE = "STABLE"
    SLOWER = "SLOWER"


class AlignmentStatus(StrEnum):
    MATCHED = "MATCHED"
    PARTIAL = "PARTIAL"
    UNMATCHED = "UNMATCHED"


@dataclass(frozen=True, slots=True)
class EquivalentSetKey:
    distance_m: int
    stroke: str
    planned_role: str
    set_id: str | None = None
    planned_intensity: str | None = None
    target_min_pace_s_per_100m: Decimal | None = None
    target_max_pace_s_per_100m: Decimal | None = None


@dataclass(frozen=True, slots=True)
class EquivalentSetAnalysis:
    key: EquivalentSetKey
    pace_basis: str
    interval_indices: tuple[int, ...]
    excluded_outlier_indices: tuple[int, ...]
    excluded_stroke_mismatch_indices: tuple[int, ...]
    missing_pace_indices: tuple[int, ...]
    paces_s_per_100m: tuple[Decimal, ...]
    mean_pace_s_per_100m: Decimal
    best_pace_s_per_100m: Decimal
    worst_pace_s_per_100m: Decimal
    amplitude_s_per_100m: Decimal
    coefficient_of_variation: Decimal | None
    trend_s_per_repetition: Decimal | None
    trend: TrendDirection
    negative_split: bool | None
    fade_percent: Decimal | None
    target_compliance_ratio: Decimal | None
    target_compliance_pace_basis: str | None
    planned_rest_duration_s: Decimal | None
    actual_rest_duration_s: Decimal | None
    quality: QualityLevel
    quality_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OutlierFlag:
    interval_index: int
    group: EquivalentSetKey
    pace_s_per_100m: Decimal
    median_pace_s_per_100m: Decimal
    modified_z_score: Decimal | None
    reason: str


@dataclass(frozen=True, slots=True)
class _CandidateSetRun:
    intervals: tuple[object, ...]
    quality_reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ContinuousBlock:
    distance_m: int
    duration_s: Decimal
    start_length_index: int
    end_length_index: int


@dataclass(frozen=True, slots=True)
class WindowPerformance:
    target_distance_m: int
    distance_m: int
    duration_s: Decimal
    pace_s_per_100m: Decimal
    start_length_index: int
    end_length_index: int
    stroke: str


@dataclass(frozen=True, slots=True)
class ContinuityAnalysis:
    longest_continuous_swim: ContinuousBlock | None
    longest_continuous_freestyle: ContinuousBlock | None
    best_windows: Mapping[int, WindowPerformance | None]
    quality: QualityLevel
    quality_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class QualityAssessment:
    level: QualityLevel
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DistanceBandProfile:
    name: str
    minimum_distance_m: int
    maximum_distance_m: int | None
    interval_count: int
    total_distance_m: int
    best_pace_s_per_100m: Decimal | None
    mean_pace_s_per_100m: Decimal | None
    quality: QualityLevel
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DimensionProfile:
    name: str
    interval_count: int
    total_distance_m: int
    longest_distance_m: int
    best_pace_s_per_100m: Decimal | None
    mean_pace_s_per_100m: Decimal | None
    gap_to_goal_pace_s_per_100m: Decimal | None
    quality: QualityLevel
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GoalReadiness:
    goal_distance_m: int
    goal_pace_s_per_100m: Decimal
    longest_evidence_distance_m: int
    evidence_pace_s_per_100m: Decimal | None
    evidence_pace_basis: str | None
    pace_gap_s_per_100m: Decimal | None
    ready: bool | None
    confidence: QualityLevel
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SpeedEnduranceProfile:
    bands: tuple[DistanceBandProfile, ...]
    speed: DimensionProfile
    short_endurance: DimensionProfile
    aerobic_endurance: DimensionProfile
    technique: DimensionProfile
    goal_readiness: GoalReadiness
    data_quality: QualityAssessment


@dataclass(frozen=True, slots=True)
class ExpandedPlannedStep:
    sequence_index: int
    step_id: str | None
    set_id: str | None
    repetition_index: int | None
    planned_role: str
    interval_type: str
    distance_m: int | None
    duration_s: Decimal | None
    stroke: str
    intensity: str | None
    target_min_pace_s_per_100m: Decimal | None
    target_max_pace_s_per_100m: Decimal | None


@dataclass(frozen=True, slots=True)
class StepAlignment:
    planned_index: int
    actual_index: int | None
    set_id: str | None
    repetition_index: int | None
    status: AlignmentStatus
    confidence: Decimal
    planned_role: str
    planned_interval_type: str
    actual_interval_type: str | None
    planned_distance_m: int | None
    actual_distance_m: int | None
    distance_difference_m: int | None
    planned_duration_s: Decimal | None
    planned_duration_min_s: Decimal | None
    planned_duration_max_s: Decimal | None
    actual_duration_s: Decimal | None
    actual_duration_basis: str | None
    duration_difference_s: Decimal | None
    duration_target_met: bool | None
    planned_pace_s_per_100m: Decimal | None
    planned_pace_min_s_per_100m: Decimal | None
    planned_pace_max_s_per_100m: Decimal | None
    planned_pace_basis: str | None
    actual_pace_s_per_100m: Decimal | None
    actual_pace_basis: str | None
    pace_difference_s_per_100m: Decimal | None
    target_pace_met: bool | None
    planned_stroke: str
    actual_stroke: str | None
    stroke_match: bool | None
    planned_intensity: str | None
    adherence_ratio: Decimal | None
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class WorkoutAdherence:
    alignments: tuple[StepAlignment, ...]
    unmatched_actual_indices: tuple[int, ...]
    planned_distance_m: int
    actual_distance_m: int
    distance_difference_m: int
    distance_adherence_ratio: Decimal | None
    matched_step_ratio: Decimal | None
    mean_alignment_confidence: Decimal | None
    quality: QualityAssessment


def _field(item: object, *names: str, default: object = None) -> object:
    if isinstance(item, Mapping):
        for name in names:
            if name in item:
                return item[name]
        return default
    for name in names:
        if hasattr(item, name):
            return getattr(item, name)
    return default


def _decimal(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, StrEnum):
        value = value.value
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return result if result.is_finite() else None


def _decimal_field(item: object, *names: str) -> Decimal | None:
    """Return the first finite numeric alias, skipping present-but-null aliases."""

    for name in names:
        value = _decimal(_field(item, name, default=None))
        if value is not None:
            return value
    return None


def _integer(value: object) -> int | None:
    number = _decimal(value)
    if number is None:
        return None
    return int(number.to_integral_value(rounding=ROUND_HALF_UP))


def _token(value: object, default: str = "UNKNOWN") -> str:
    if isinstance(value, StrEnum):
        value = value.value
    if value is None:
        return default
    text = str(value).strip().upper().replace("-", "_").replace(" ", "_")
    return text or default


def _stroke(item_or_value: object) -> str:
    value = item_or_value
    if isinstance(value, Mapping) or not isinstance(value, (str, StrEnum)):
        nested_type = _field(value, "type", default=None)
        if nested_type is not None:
            value = nested_type
        else:
            value = _field(
                value,
                "detected_stroke",
                "stroke_type",
                "stroke",
                "planned_stroke",
                default=None,
            )
            nested_type = _field(value, "type", default=None)
            if nested_type is not None:
                value = nested_type
    token = _token(value)
    aliases = {
        "CRAWL": "FREESTYLE",
        "FRONT_CRAWL": "FREESTYLE",
        "FREE": "FREESTYLE",
        "BACK": "BACKSTROKE",
        "BREAST": "BREASTSTROKE",
        "FLY": "BUTTERFLY",
    }
    return aliases.get(token, token)


_INDETERMINATE_STROKES: Final[frozenset[str]] = frozenset({"UNKNOWN", "MIXED", "CHOICE"})


def _specific_planned_stroke(item: object) -> str | None:
    planned = _stroke(_field(item, "planned_stroke", default=None))
    return None if planned in _INDETERMINATE_STROKES else planned


def _set_stroke(item: object) -> str:
    """Use a specific prescription as set context without erasing detection.

    Garmin commonly reports MIXED for a prescribed single-stroke repetition.
    Such an indeterminate detection can remain comparable under the planned
    stroke. A conflicting explicit detected stroke is retained as a mismatch and
    excluded from pace/fade below.
    """

    return _specific_planned_stroke(item) or _stroke(item)


def _planned_detected_stroke_mismatch(item: object) -> bool:
    planned = _specific_planned_stroke(item)
    detected = _stroke(item)
    return planned is not None and detected not in _INDETERMINATE_STROKES and detected != planned


def planned_stroke_context_used(item: object) -> bool:
    """Whether a specific prescription contextualizes MIXED/UNKNOWN detection."""

    return _specific_planned_stroke(item) is not None and _stroke(item) in _INDETERMINATE_STROKES


def _role(item: object) -> str:
    return _token(_field(item, "planned_role", "step_role", "role", default=None))


def _interval_type(item: object) -> str:
    token = _token(_field(item, "interval_type", "length_type", "type", default=None))
    aliases = {"WORK": "SWIM", "ACTIVE": "SWIM", "IDLE": "REST"}
    return aliases.get(token, token)


def _distance(item: object) -> int:
    return max(0, _integer(_field(item, "distance_m", "meters", default=0)) or 0)


def _index(item: object, fallback: int) -> int:
    return (
        _integer(_field(item, "interval_index", "length_index", "sequence_index", default=fallback))
        or 0
    )


def _round(value: Decimal, quantum: Decimal = _MILLISECOND) -> Decimal:
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


_PACE_FIELDS: Final[dict[str, tuple[str, ...]]] = {
    "moving": (
        "moving_pace_s_per_100m",
        "moving_pace_seconds_per_100m",
    ),
    "swim": (
        "swim_pace_s_per_100m",
        "swim_pace_seconds_per_100m",
    ),
    "timer": (
        "timer_pace_s_per_100m",
        "timer_pace_seconds_per_100m",
        "pace_seconds_per_100m",  # legacy field whose historic basis was timer
    ),
    "garmin": (
        "pace_from_garmin_reported_speed_s_per_100m",
        "pace_from_garmin_reported_speed_seconds_per_100m",
    ),
}


def pace_for(item: object, *, basis: str = "moving") -> Decimal | None:
    """Read one explicit pace basis without falling back to a different basis."""

    try:
        names = _PACE_FIELDS[basis.lower()]
    except KeyError as error:
        raise ValueError(f"unsupported pace basis: {basis}") from error
    value = _decimal_field(item, *names)
    return value if value is not None and value > 0 else None


def format_seconds_mmss(seconds: Decimal | int | float | str) -> str:
    """Round half-up and format a non-negative duration as unbounded ``mm:ss``."""

    value = _decimal(seconds)
    if value is None or value < 0:
        raise ValueError("duration must be a finite non-negative number")
    total_seconds = int(value.to_integral_value(rounding=ROUND_HALF_UP))
    minutes, remaining_seconds = divmod(total_seconds, 60)
    return f"{minutes}:{remaining_seconds:02d}"


def freestyle_work_intervals(
    intervals: Iterable[object],
    *,
    include_outliers: bool = False,
) -> tuple[object, ...]:
    """Return only freestyle swim intervals explicitly carrying the WORK role."""

    selected: list[object] = []
    for item in intervals:
        if _distance(item) <= 0:
            continue
        if _interval_type(item) != "SWIM":
            continue
        if _role(item) != "WORK" or _set_stroke(item) != "FREESTYLE":
            continue
        if _planned_detected_stroke_mismatch(item):
            continue
        if not include_outliers and _fitness_excluded(item):
            continue
        selected.append(item)
    return tuple(selected)


def _fitness_excluded(item: object) -> bool:
    """Honor an explicit, persistible exclusion marker without inferring bad data.

    ``quality_warnings`` already belongs to the canonical persisted interval model,
    so ``EXCLUDE_FROM_FITNESS`` can survive reprocessing without a schema change.
    Boolean ``is_outlier``/``outlier`` remain accepted for callers using the older
    analysis-only mapping shape.
    """

    if bool(
        _field(
            item,
            "exclude_from_fitness",
            "is_outlier",
            "outlier",
            default=False,
        )
    ):
        return True
    warnings = _field(item, "quality_warnings", default=())
    if not isinstance(warnings, Sequence) or isinstance(warnings, (str, bytes, bytearray)):
        return False
    return any(str(warning).strip().upper() == "EXCLUDE_FROM_FITNESS" for warning in warnings)


def _mean(values: Sequence[Decimal]) -> Decimal:
    return sum(values, _ZERO) / Decimal(len(values))


def _cv(values: Sequence[Decimal]) -> Decimal | None:
    if len(values) < 2:
        return None
    mean_value = _mean(values)
    if mean_value == 0:
        return None
    variance = sum(((value - mean_value) ** 2 for value in values), _ZERO) / Decimal(len(values))
    return _round(variance.sqrt() / mean_value, _FOUR_PLACES)


def _slope(values: Sequence[Decimal]) -> Decimal | None:
    if len(values) < 2:
        return None
    x_mean = Decimal(len(values) - 1) / Decimal(2)
    y_mean = _mean(values)
    numerator = sum(
        ((Decimal(index) - x_mean) * (value - y_mean) for index, value in enumerate(values)),
        _ZERO,
    )
    denominator = sum(((Decimal(index) - x_mean) ** 2 for index in range(len(values))), _ZERO)
    return _round(numerator / denominator) if denominator else None


def _halves(values: Sequence[Decimal]) -> tuple[Decimal, Decimal] | None:
    half_size = len(values) // 2
    if half_size == 0:
        return None
    return _mean(values[:half_size]), _mean(values[-half_size:])


def _target_range(item: object) -> tuple[Decimal, Decimal] | None:
    minimum = _decimal(
        _field(
            item,
            "target_min_pace_s_per_100m",
            "planned_pace_min_s_per_100m",
            default=None,
        )
    )
    maximum = _decimal(
        _field(
            item,
            "target_max_pace_s_per_100m",
            "planned_pace_max_s_per_100m",
            default=None,
        )
    )
    target = _field(item, "target", default=None)
    minimum = minimum or _decimal(_field(target, "min_seconds_per_100m", default=None))
    maximum = maximum or _decimal(_field(target, "max_seconds_per_100m", default=None))
    if minimum is None or maximum is None or minimum <= 0 or maximum < minimum:
        return None
    return minimum, maximum


def _set_key(item: object) -> EquivalentSetKey:
    raw_set_id = _field(item, "set_id", "planned_set_id", default=None)
    raw_intensity = _field(item, "planned_intensity", "intensity", default=None)
    target = _target_range(item)
    return EquivalentSetKey(
        distance_m=_distance(item),
        stroke=_set_stroke(item),
        planned_role=_role(item),
        set_id=str(raw_set_id) if raw_set_id is not None else None,
        planned_intensity=_token(raw_intensity) if raw_intensity is not None else None,
        target_min_pace_s_per_100m=target[0] if target is not None else None,
        target_max_pace_s_per_100m=target[1] if target is not None else None,
    )


def _rest_boundary_duration(item: object) -> Decimal | None:
    return _decimal_field(
        item,
        "rest_duration_s",
        "rest_seconds",
        "timer_duration_s",
        "timer_seconds",
        "duration_seconds",
    )


def _candidate_set_runs(intervals: Sequence[object]) -> tuple[_CandidateSetRun, ...]:
    """Build equivalent runs while preserving normal repetition recovery.

    Without planned set identity, a rest of at least 60 seconds is treated as an
    inferred set boundary.  The threshold is deliberately conservative relative to
    normal repetition rests and its uncertainty is disclosed on both adjacent runs.
    """

    boundary_reason = "UNPLANNED_LONG_REST_SET_BOUNDARY_INFERRED"
    runs: list[_CandidateSetRun] = []
    current: list[object] = []
    current_key: EquivalentSetKey | None = None
    current_reasons: tuple[str, ...] = ()
    pending_boundary_reason = False
    for item in intervals:
        item_type = _interval_type(item)
        role = _role(item)
        if item_type == "REST" or role == "REST" or _distance(item) == 0:
            rest_duration = _rest_boundary_duration(item)
            if (
                current
                and current_key is not None
                and current_key.set_id is None
                and rest_duration is not None
                and rest_duration >= _UNPLANNED_SET_BOUNDARY_REST_S
            ):
                runs.append(
                    _CandidateSetRun(
                        tuple(current),
                        tuple(dict.fromkeys((*current_reasons, boundary_reason))),
                    )
                )
                current = []
                current_key = None
                current_reasons = ()
                pending_boundary_reason = True
            continue
        if item_type not in {"SWIM", "UNKNOWN"} or role in {"DRILL", "COOLDOWN"}:
            if current:
                runs.append(_CandidateSetRun(tuple(current), current_reasons))
                current = []
                current_key = None
                current_reasons = ()
            pending_boundary_reason = False
            continue
        key = _set_key(item)
        if current_key == key:
            current.append(item)
            continue
        if current:
            runs.append(_CandidateSetRun(tuple(current), current_reasons))
        current = [item]
        current_key = key
        current_reasons = (
            (boundary_reason,) if pending_boundary_reason and key.set_id is None else ()
        )
        pending_boundary_reason = False
    if current:
        runs.append(_CandidateSetRun(tuple(current), current_reasons))
    return tuple(runs)


def _rest_like(item: object) -> bool:
    return _interval_type(item) == "REST" or _role(item) == "REST" or _distance(item) == 0


def _explicit_rests_for_run(
    run: Sequence[object],
    records: Sequence[object],
    positions: Mapping[int, int],
    *,
    exclude_unplanned_boundary_rest: bool = False,
) -> tuple[object, ...]:
    """Return rests between repetitions plus trailing rests before the next swim block."""

    start = positions[id(run[0])]
    end = positions[id(run[-1])]
    while end + 1 < len(records) and _rest_like(records[end + 1]):
        end += 1
    rests = tuple(item for item in records[start : end + 1] if _rest_like(item))
    if not exclude_unplanned_boundary_rest:
        return rests
    return tuple(
        item
        for item in rests
        if (duration := _rest_boundary_duration(item)) is None
        or duration < _UNPLANNED_SET_BOUNDARY_REST_S
    )


def _outlier_positions(
    paces: Sequence[Decimal],
    *,
    modified_z_threshold: Decimal,
    zero_mad_relative_threshold: Decimal,
) -> dict[int, tuple[Decimal | None, str]]:
    if len(paces) < 4:
        return {}
    median_value = median(paces)
    deviations = tuple(abs(value - median_value) for value in paces)
    mad = median(deviations)
    flagged: dict[int, tuple[Decimal | None, str]] = {}
    if mad > 0:
        for index, value in enumerate(paces):
            modified_z = Decimal("0.6745") * (value - median_value) / mad
            if abs(modified_z) > modified_z_threshold:
                flagged[index] = (_round(modified_z, _HUNDREDTH), "ROBUST_MAD_OUTLIER")
        return flagged
    if median_value <= 0:
        return flagged
    for index, value in enumerate(paces):
        relative_difference = abs(value - median_value) / median_value
        if relative_difference > zero_mad_relative_threshold:
            flagged[index] = (None, "ZERO_MAD_LARGE_DEVIATION")
    return flagged


def detect_interval_outliers(
    intervals: Iterable[object],
    *,
    pace_basis: str = "moving",
    modified_z_threshold: Decimal = Decimal("3.5"),
    zero_mad_relative_threshold: Decimal = Decimal("0.20"),
) -> tuple[OutlierFlag, ...]:
    """Flag pace outliers only within contiguous, distance/stroke/role-equivalent runs."""

    if modified_z_threshold <= 0 or zero_mad_relative_threshold <= 0:
        raise ValueError("outlier thresholds must be positive")
    records = tuple(intervals)
    flags: list[OutlierFlag] = []
    positions = {id(item): index for index, item in enumerate(records)}
    for candidate_run in _candidate_set_runs(records):
        run = candidate_run.intervals
        comparable_items: list[tuple[object, Decimal]] = []
        for item in run:
            if _planned_detected_stroke_mismatch(item):
                continue
            pace = pace_for(item, basis=pace_basis)
            if pace is not None:
                comparable_items.append((item, pace))
        comparable = tuple(comparable_items)
        if not comparable:
            continue
        paces = tuple(pace for _, pace in comparable)
        median_value = median(paces)
        flagged = _outlier_positions(
            paces,
            modified_z_threshold=modified_z_threshold,
            zero_mad_relative_threshold=zero_mad_relative_threshold,
        )
        for comparable_index, (modified_z, reason) in flagged.items():
            item, pace = comparable[comparable_index]
            fallback = positions[id(item)]
            flags.append(
                OutlierFlag(
                    interval_index=_index(item, fallback),
                    group=_set_key(item),
                    pace_s_per_100m=pace,
                    median_pace_s_per_100m=_round(median_value),
                    modified_z_score=modified_z,
                    reason=reason,
                )
            )
    return tuple(flags)


def group_equivalent_sets(
    intervals: Iterable[object],
    *,
    pace_basis: str = "moving",
    minimum_repetitions: int = 2,
    trend_tolerance_s_per_repetition: Decimal = Decimal("0.5"),
) -> tuple[EquivalentSetAnalysis, ...]:
    """Analyze contiguous equivalent repetitions without mixing roles, strokes or distances."""

    if minimum_repetitions < 2:
        raise ValueError("minimum repetitions must be at least two")
    if trend_tolerance_s_per_repetition < 0:
        raise ValueError("trend tolerance cannot be negative")
    records = tuple(intervals)
    analyses: list[EquivalentSetAnalysis] = []
    positions = {id(item): index for index, item in enumerate(records)}
    for candidate_run in _candidate_set_runs(records):
        run = candidate_run.intervals
        if len(run) < minimum_repetitions:
            continue
        selected_basis = pace_basis
        if pace_basis == "best_available":
            basis_priority = ("moving", "swim", "timer")
            coverage = {
                candidate: sum(
                    pace_for(item, basis=candidate) is not None
                    for item in run
                    if not _fitness_excluded(item) and not _planned_detected_stroke_mismatch(item)
                )
                for candidate in basis_priority
            }
            selected_basis = max(
                basis_priority,
                key=lambda candidate: (coverage[candidate], -basis_priority.index(candidate)),
            )
            if coverage[selected_basis] < minimum_repetitions:
                continue
        values: list[Decimal] = []
        indices: list[int] = []
        excluded: list[int] = []
        excluded_stroke_mismatches: list[int] = []
        missing_pace: list[int] = []
        attached_planned_rests: list[Decimal] = []
        attached_actual_rests: list[Decimal] = []
        for item in run:
            index = _index(item, positions[id(item)])
            pace = pace_for(item, basis=selected_basis)
            marked_outlier = _fitness_excluded(item)
            # A statistical outlier is evidence to inspect, not proof of bad
            # measurement. Exclusion requires an explicit upstream quality flag.
            if marked_outlier:
                excluded.append(index)
                continue
            if _planned_detected_stroke_mismatch(item):
                excluded_stroke_mismatches.append(index)
                continue
            if pace is None:
                missing_pace.append(index)
                continue
            indices.append(index)
            values.append(pace)
            planned_rest = _decimal_field(item, "planned_rest_duration_s", "planned_rest_seconds")
            actual_rest = _decimal_field(item, "rest_duration_s", "rest_seconds")
            if planned_rest is not None and planned_rest >= 0:
                attached_planned_rests.append(planned_rest)
            if actual_rest is not None and actual_rest >= 0:
                attached_actual_rests.append(actual_rest)
        if len(values) < minimum_repetitions:
            continue
        mean_value = _mean(values)
        best = min(values)
        worst = max(values)
        slope = _slope(values)
        if slope is None or abs(slope) <= trend_tolerance_s_per_repetition:
            trend = TrendDirection.STABLE
        elif slope < 0:
            trend = TrendDirection.FASTER
        else:
            trend = TrendDirection.SLOWER
        unknown_interval_type = any(_interval_type(item) == "UNKNOWN" for item in run)
        halves = _halves(values)
        negative_split = halves[1] < halves[0] if halves is not None else None
        fade = (
            _round((halves[1] - halves[0]) / halves[0] * Decimal(100), _HUNDREDTH)
            if halves is not None and halves[0] > 0 and not unknown_interval_type
            else None
        )
        target_results: list[bool] = []
        target_basis_missing = False
        target_present = False
        for item in run:
            if _fitness_excluded(item) or _planned_detected_stroke_mismatch(item):
                continue
            target = _target_range(item)
            if target is None:
                continue
            target_present = True
            target_pace = pace_for(item, basis="swim")
            if target_pace is None:
                target_basis_missing = True
                continue
            minimum, maximum = target
            target_results.append(minimum <= target_pace <= maximum)
        compliance = (
            _round(Decimal(sum(target_results)) / Decimal(len(target_results)), _FOUR_PLACES)
            if target_results and not target_basis_missing
            else None
        )
        explicit_planned_rests: list[Decimal] = []
        explicit_actual_rests: list[Decimal] = []
        for rest in _explicit_rests_for_run(
            run,
            records,
            positions,
            exclude_unplanned_boundary_rest=_set_key(run[0]).set_id is None,
        ):
            planned_rest = _decimal_field(
                rest,
                "planned_rest_duration_s",
                "planned_rest_seconds",
                "planned_duration_s",
            )
            actual_rest = _decimal_field(rest, "rest_duration_s", "rest_seconds")
            if actual_rest is None and _interval_type(rest) == "REST":
                actual_rest = _decimal_field(
                    rest, "timer_duration_s", "timer_seconds", "duration_seconds"
                )
            if planned_rest is not None and planned_rest >= 0:
                explicit_planned_rests.append(planned_rest)
            if actual_rest is not None and actual_rest >= 0:
                explicit_actual_rests.append(actual_rest)
        planned_rests = explicit_planned_rests or attached_planned_rests
        actual_rests = explicit_actual_rests or attached_actual_rests
        quality_reasons: list[str] = list(candidate_run.quality_reasons)
        if unknown_interval_type:
            quality_reasons.append("UNKNOWN_INTERVAL_TYPE_IN_SET")
        if selected_basis != "moving":
            quality_reasons.append(f"SET_USES_{selected_basis.upper()}_PACE")
        if missing_pace:
            quality_reasons.append(f"MISSING_{selected_basis.upper()}_PACE_FOR_REPETITIONS")
        if len(values) < 4:
            quality_reasons.append("LIMITED_EQUIVALENT_REPETITIONS")
        if excluded:
            quality_reasons.append("LOW_QUALITY_REPETITIONS_EXCLUDED")
        if excluded_stroke_mismatches:
            quality_reasons.append("DETECTED_STROKE_MISMATCH_EXCLUDED")
        if any(planned_stroke_context_used(item) for item in run):
            quality_reasons.append("PLANNED_STROKE_CONTEXT_USED")
        if target_present:
            quality_reasons.append("PLANNED_PACE_BASIS_INFERRED_SWIM")
        if target_basis_missing:
            quality_reasons.append("TARGET_SWIM_PACE_UNAVAILABLE")
        if (
            len(values) >= 4
            and selected_basis == "moving"
            and not excluded
            and not excluded_stroke_mismatches
            and not missing_pace
            and not candidate_run.quality_reasons
            and not unknown_interval_type
            and not target_basis_missing
            and not target_present
        ):
            set_quality = QualityLevel.HIGH
        elif len(values) >= 3 and selected_basis in {"moving", "swim"}:
            set_quality = QualityLevel.MEDIUM
        else:
            set_quality = QualityLevel.LOW
        analyses.append(
            EquivalentSetAnalysis(
                key=_set_key(run[0]),
                pace_basis=selected_basis,
                interval_indices=tuple(indices),
                excluded_outlier_indices=tuple(excluded),
                excluded_stroke_mismatch_indices=tuple(excluded_stroke_mismatches),
                missing_pace_indices=tuple(missing_pace),
                paces_s_per_100m=tuple(_round(value) for value in values),
                mean_pace_s_per_100m=_round(mean_value),
                best_pace_s_per_100m=_round(best),
                worst_pace_s_per_100m=_round(worst),
                amplitude_s_per_100m=_round(worst - best),
                coefficient_of_variation=_cv(values),
                trend_s_per_repetition=slope,
                trend=trend,
                negative_split=negative_split,
                fade_percent=fade,
                target_compliance_ratio=compliance,
                target_compliance_pace_basis="swim" if target_present else None,
                planned_rest_duration_s=(
                    _round(sum(planned_rests, _ZERO)) if planned_rests else None
                ),
                actual_rest_duration_s=(_round(sum(actual_rests, _ZERO)) if actual_rests else None),
                quality=set_quality,
                quality_reasons=tuple(quality_reasons),
            )
        )
    return tuple(analyses)


def _length_is_active(item: object) -> bool:
    item_type = _interval_type(item)
    role = _role(item)
    return _distance(item) > 0 and item_type not in {"REST", "IDLE"} and role != "REST"


def _break_before(item: object) -> bool:
    explicit = bool(
        _field(item, "continuity_break_before", "starts_new_continuous_block", default=False)
    )
    rest = _decimal(_field(item, "rest_duration_s", "rest_seconds", default=None))
    return explicit or (rest is not None and rest > 0)


def _has_stationary_pause(item: object) -> bool:
    """Treat a positive canonical stationary fact as a real continuity boundary.

    The normalized field is already rounded to milliseconds.  Analytics must not
    invent a second tolerance that could bridge a genuine pause; clock noise should
    instead be resolved (and disclosed) by normalization before it becomes a fact.
    """

    stationary = _decimal_field(item, "stationary_duration_s", "stationary_seconds")
    return stationary is not None and stationary > 0


def _has_uncertain_continuity_boundary(item: object) -> bool:
    return bool(_field(item, "continuity_boundary_uncertain", default=False))


def _length_duration(item: object) -> Decimal | None:
    value = _decimal_field(
        item,
        "swim_duration_s",
        "swim_seconds",
        "moving_duration_s",
        "moving_seconds",
        "duration_seconds",
        "timer_duration_s",
        "timer_seconds",
    )
    return value if value is not None and value >= 0 else None


def _continuous_blocks(
    lengths: Sequence[object], *, freestyle_only: bool
) -> tuple[tuple[object, ...], ...]:
    blocks: list[tuple[object, ...]] = []
    current: list[object] = []
    for item in lengths:
        active = _length_is_active(item)
        stroke_ok = _stroke(item) == "FREESTYLE" if freestyle_only else True
        role_ok = _role(item) not in {"DRILL", "COOLDOWN"} if freestyle_only else True
        isolating_boundary = _has_stationary_pause(item) or _has_uncertain_continuity_boundary(item)
        if (_break_before(item) or isolating_boundary) and current:
            blocks.append(tuple(current))
            current = []
        if active and stroke_ok and role_ok and _length_duration(item) is not None:
            current.append(item)
            # The location of stationary time inside a Garmin length is unknown.
            # Isolating the length prevents a continuous block/window from crossing
            # the pause in either direction while preserving the observed swim.
            if isolating_boundary:
                blocks.append(tuple(current))
                current = []
        elif current:
            blocks.append(tuple(current))
            current = []
    if current:
        blocks.append(tuple(current))
    return tuple(blocks)


def _block_summary(block: Sequence[object], positions: Mapping[int, int]) -> ContinuousBlock:
    return ContinuousBlock(
        distance_m=sum(_distance(item) for item in block),
        duration_s=_round(sum((_length_duration(item) or _ZERO for item in block), _ZERO)),
        start_length_index=_index(block[0], positions[id(block[0])]),
        end_length_index=_index(block[-1], positions[id(block[-1])]),
    )


def _best_exact_window(
    blocks: Sequence[Sequence[object]],
    *,
    target_distance_m: int,
    positions: Mapping[int, int],
) -> WindowPerformance | None:
    best: WindowPerformance | None = None
    for block in blocks:
        left = 0
        distance = 0
        duration = _ZERO
        for right, item in enumerate(block):
            distance += _distance(item)
            duration += _length_duration(item) or _ZERO
            while distance > target_distance_m and left <= right:
                distance -= _distance(block[left])
                duration -= _length_duration(block[left]) or _ZERO
                left += 1
            if distance != target_distance_m or duration <= 0:
                continue
            pace = _round(duration / Decimal(distance) * Decimal(100))
            candidate = WindowPerformance(
                target_distance_m=target_distance_m,
                distance_m=distance,
                duration_s=_round(duration),
                pace_s_per_100m=pace,
                start_length_index=_index(block[left], positions[id(block[left])]),
                end_length_index=_index(item, positions[id(item)]),
                stroke="FREESTYLE",
            )
            if best is None or candidate.pace_s_per_100m < best.pace_s_per_100m:
                best = candidate
    return best


def analyze_continuity(
    lengths: Iterable[object],
    *,
    window_distances_m: Sequence[int] = (100, 200, 400, 800),
) -> ContinuityAnalysis:
    """Measure real contiguous swims and exact freestyle windows; never extrapolate."""

    if any(distance <= 0 for distance in window_distances_m):
        raise ValueError("window distances must be positive")
    records = tuple(lengths)
    positions = {id(item): position for position, item in enumerate(records)}
    swim_blocks = _continuous_blocks(records, freestyle_only=False)
    free_blocks = _continuous_blocks(records, freestyle_only=True)
    swim_summaries = tuple(_block_summary(block, positions) for block in swim_blocks)
    free_summaries = tuple(_block_summary(block, positions) for block in free_blocks)
    longest_swim = max(swim_summaries, key=lambda block: block.distance_m, default=None)
    longest_free = max(free_summaries, key=lambda block: block.distance_m, default=None)
    windows = {
        distance: _best_exact_window(free_blocks, target_distance_m=distance, positions=positions)
        for distance in dict.fromkeys(window_distances_m)
    }
    reasons: list[str] = []
    if not records:
        reasons.append("NO_LENGTH_DATA")
    if any(_length_duration(item) is None for item in records if _length_is_active(item)):
        reasons.append("MISSING_LENGTH_DURATION")
    if any(_has_uncertain_continuity_boundary(item) for item in records):
        reasons.append("INTERVAL_STATIONARY_LOCATION_UNKNOWN")
    if not free_blocks:
        reasons.append("NO_CONTINUOUS_FREESTYLE_DATA")
    for distance, performance in windows.items():
        if performance is None:
            reasons.append(f"NO_CONTIGUOUS_{distance}M_WINDOW")
    if longest_swim is None or longest_free is None:
        quality = QualityLevel.LOW
    elif reasons:
        quality = QualityLevel.MEDIUM
    else:
        quality = QualityLevel.HIGH
    return ContinuityAnalysis(
        longest_continuous_swim=longest_swim,
        longest_continuous_freestyle=longest_free,
        best_windows=windows,
        quality=quality,
        quality_reasons=tuple(reasons),
    )


def assess_data_quality(
    activity: object | None = None,
    *,
    intervals: Iterable[object] = (),
    lengths: Iterable[object] = (),
    alignments: Iterable[StepAlignment] = (),
    pool_length_inferred: bool = False,
    warnings: Iterable[str] = (),
) -> QualityAssessment:
    """Return stable data-quality reason codes and a conservative evidence level."""

    interval_records = tuple(intervals)
    length_records = tuple(lengths)
    alignment_records = tuple(alignments)
    reasons = list(dict.fromkeys(str(warning) for warning in warnings))
    severe = False
    moving = (
        _decimal_field(activity, "moving_duration_s", "moving_seconds")
        if activity is not None
        else None
    )
    timer = (
        _decimal_field(activity, "timer_duration_s", "timer_seconds")
        if activity is not None
        else None
    )
    elapsed = (
        _decimal_field(activity, "elapsed_duration_s", "elapsed_seconds")
        if activity is not None
        else None
    )
    distance = (
        _integer(_field(activity, "distance_m", default=None)) if activity is not None else None
    )
    pool = (
        _integer(_field(activity, "pool_length_m", default=None)) if activity is not None else None
    )
    active_count = (
        _integer(_field(activity, "active_length_count", default=None))
        if activity is not None
        else None
    )
    normalization_quality = (
        _token(_field(activity, "quality", default=None)) if activity is not None else "UNKNOWN"
    )
    completeness = _decimal_field(activity, "completeness") if activity is not None else None
    if normalization_quality == "POOR" or (
        completeness is not None and completeness < Decimal("0.5")
    ):
        reasons.append("NORMALIZATION_QUALITY_POOR")
        severe = True
    elif normalization_quality == "PARTIAL" or (
        completeness is not None and completeness < Decimal("0.8")
    ):
        reasons.append("NORMALIZATION_QUALITY_PARTIAL")
    if activity is not None and moving is None:
        reasons.append("MISSING_MOVING_DURATION")
    if any(value is not None and value < 0 for value in (moving, timer, elapsed)):
        reasons.append("NEGATIVE_DURATION")
        severe = True
    if moving is not None and timer is not None and moving > timer:
        reasons.append("MOVING_EXCEEDS_TIMER")
        severe = True
    if timer is not None and elapsed is not None and timer > elapsed:
        reasons.append("TIMER_EXCEEDS_ELAPSED")
        severe = True
    if activity is not None and (pool is None or pool <= 0):
        reasons.append("POOL_LENGTH_MISSING")
        severe = True
    if pool_length_inferred:
        reasons.append("POOL_LENGTH_INFERRED")
    if (
        pool is not None
        and pool > 0
        and active_count is not None
        and distance is not None
        and pool * active_count != distance
    ):
        reasons.append("ACTIVE_LENGTH_DISTANCE_MISMATCH")
    if interval_records and any(
        _distance(item) > 0 and _stroke(item) == "UNKNOWN" for item in interval_records
    ):
        reasons.append("UNKNOWN_STROKE")
    pace_differences = 0
    for item in interval_records:
        garmin_pace = pace_for(item, basis="garmin")
        timer_pace = pace_for(item, basis="timer")
        if (
            garmin_pace is not None
            and timer_pace is not None
            and abs(garmin_pace - timer_pace) > Decimal("5")
        ):
            pace_differences += 1
    if pace_differences:
        reasons.append("GARMIN_TIMER_PACE_DIFFERENCE")
    if detect_interval_outliers(interval_records):
        reasons.append("PACE_OUTLIERS_DETECTED")
    if alignment_records and any(
        alignment.status is AlignmentStatus.UNMATCHED for alignment in alignment_records
    ):
        reasons.append("WORKOUT_STEP_UNMATCHED")
    if alignment_records and any(
        alignment.status is AlignmentStatus.PARTIAL for alignment in alignment_records
    ):
        reasons.append("WORKOUT_STEP_PARTIAL")
    if not length_records:
        reasons.append("NO_LENGTH_DATA")
    if any(_has_uncertain_continuity_boundary(item) for item in length_records):
        reasons.append("INTERVAL_STATIONARY_LOCATION_UNKNOWN")
    comparable = freestyle_work_intervals(interval_records)
    if len(comparable) < 2:
        reasons.append("INSUFFICIENT_COMPARABLE_INTERVALS")
    unique_reasons = tuple(dict.fromkeys(reasons))
    if severe or len(unique_reasons) >= 5:
        level = QualityLevel.LOW
    elif unique_reasons:
        level = QualityLevel.MEDIUM
    else:
        level = QualityLevel.HIGH
    return QualityAssessment(level=level, reasons=unique_reasons)


_DISTANCE_BANDS: Final[tuple[tuple[str, int, int | None], ...]] = (
    ("40m_speed", 1, 60),
    ("80m_speed_endurance", 61, 99),
    ("100_120m_short_endurance", 100, 139),
    ("160_200m_endurance", 140, 299),
    ("400m_aerobic", 300, 599),
    ("800m_aerobic", 600, 999),
    ("1000m_plus_long_endurance", 1000, None),
)


def _dimension(
    name: str,
    records: Sequence[object],
    *,
    pace_basis: str,
    goal_pace: Decimal | None,
    minimum_evidence: int,
) -> DimensionProfile:
    paces = tuple(
        pace for item in records if (pace := pace_for(item, basis=pace_basis)) is not None
    )
    distances = tuple(_distance(item) for item in records)
    reasons: list[str] = []
    if not records:
        reasons.append("NO_COMPARABLE_EVIDENCE")
        quality = QualityLevel.LOW
    elif len(paces) < len(records):
        reasons.append("MISSING_SELECTED_PACE_BASIS")
        quality = QualityLevel.LOW if not paces else QualityLevel.MEDIUM
    elif len(records) < minimum_evidence:
        reasons.append("LIMITED_SAMPLE")
        quality = QualityLevel.MEDIUM
    else:
        quality = QualityLevel.HIGH
    mean_pace = _round(_mean(paces)) if paces else None
    return DimensionProfile(
        name=name,
        interval_count=len(records),
        total_distance_m=sum(distances),
        longest_distance_m=max(distances, default=0),
        best_pace_s_per_100m=_round(min(paces)) if paces else None,
        mean_pace_s_per_100m=mean_pace,
        gap_to_goal_pace_s_per_100m=(
            _round(mean_pace - goal_pace)
            if mean_pace is not None and goal_pace is not None
            else None
        ),
        quality=quality,
        reasons=tuple(reasons),
    )


def _technique_evidence_dimension(lengths: Sequence[object]) -> DimensionProfile:
    """Summarize comparable efficiency evidence without turning pace into a technique score.

    Stroke count and SWOLF are only meaningful in context.  This summary therefore
    keeps active, known-stroke lengths outside drill/cooldown/rest roles and reports
    their explicit swim pace as supporting context.  It deliberately exposes no gap
    to the goal pace and makes no claim that a lower SWOLF is intrinsically better.
    """

    records = tuple(
        item
        for item in lengths
        if _length_is_active(item)
        and _stroke(item) not in {"UNKNOWN", "MIXED", "DRILL"}
        and _role(item) not in {"DRILL", "COOLDOWN", "REST"}
        and (
            _integer(_field(item, "stroke_count", default=None)) is not None
            or _decimal_field(item, "swolf") is not None
        )
    )
    paces = tuple(pace for item in records if (pace := pace_for(item, basis="swim")) is not None)
    distances = tuple(_distance(item) for item in records)
    reasons = ["CONTEXTUAL_EFFICIENCY_EVIDENCE_ONLY"]
    if not records:
        reasons.append("NO_CONTEXTUAL_STROKE_EVIDENCE")
        quality = QualityLevel.LOW
    elif len(paces) < len(records):
        reasons.append("MISSING_SWIM_PACE_CONTEXT")
        quality = QualityLevel.LOW if not paces else QualityLevel.MEDIUM
    elif len(records) < 6:
        reasons.append("LIMITED_SAMPLE")
        quality = QualityLevel.MEDIUM
    else:
        quality = QualityLevel.HIGH
    mean_pace = _round(_mean(paces)) if paces else None
    return DimensionProfile(
        name="contextual_efficiency_evidence",
        interval_count=len(records),
        total_distance_m=sum(distances),
        longest_distance_m=max(distances, default=0),
        best_pace_s_per_100m=_round(min(paces)) if paces else None,
        mean_pace_s_per_100m=mean_pace,
        gap_to_goal_pace_s_per_100m=None,
        quality=quality,
        reasons=tuple(reasons),
    )


def build_speed_endurance_profile(
    intervals: Iterable[object],
    *,
    lengths: Iterable[object] = (),
    activity: object | None = None,
    pace_basis: str = "moving",
    goal_distance_m: int = 2_000,
    goal_pace_s_per_100m: Decimal = Decimal("135"),
) -> SpeedEnduranceProfile:
    """Build an evidence profile by comparable distance; this never estimates CSS."""

    if goal_distance_m <= 0 or goal_pace_s_per_100m <= 0:
        raise ValueError("goal distance and pace must be positive")
    all_intervals = tuple(intervals)
    records = tuple(freestyle_work_intervals(all_intervals))
    comparable = tuple(
        item
        for item in records
        if not _fitness_excluded(item) and pace_for(item, basis=pace_basis) is not None
    )
    bands: list[DistanceBandProfile] = []
    for name, minimum, maximum in _DISTANCE_BANDS:
        selected = tuple(
            item
            for item in comparable
            if _distance(item) >= minimum and (maximum is None or _distance(item) <= maximum)
        )
        paces = tuple(pace_for(item, basis=pace_basis) for item in selected)
        valid_paces = tuple(pace for pace in paces if pace is not None)
        band_reasons: list[str] = []
        if not selected:
            band_quality = QualityLevel.LOW
            band_reasons.append("NO_COMPARABLE_EVIDENCE")
        elif len(selected) < 2:
            band_quality = QualityLevel.MEDIUM
            band_reasons.append("LIMITED_SAMPLE")
        elif len(valid_paces) < len(selected):
            band_quality = QualityLevel.MEDIUM
            band_reasons.append("MISSING_SELECTED_PACE_BASIS")
        else:
            band_quality = QualityLevel.HIGH
        bands.append(
            DistanceBandProfile(
                name=name,
                minimum_distance_m=minimum,
                maximum_distance_m=maximum,
                interval_count=len(selected),
                total_distance_m=sum(_distance(item) for item in selected),
                best_pace_s_per_100m=(_round(min(valid_paces)) if valid_paces else None),
                mean_pace_s_per_100m=(_round(_mean(valid_paces)) if valid_paces else None),
                quality=band_quality,
                reasons=tuple(band_reasons),
            )
        )
    speed_records = tuple(item for item in comparable if _distance(item) <= 120)
    short_records = tuple(item for item in comparable if 121 <= _distance(item) < 400)
    aerobic_records = tuple(item for item in comparable if _distance(item) >= 400)
    speed = _dimension(
        "speed",
        speed_records,
        pace_basis=pace_basis,
        goal_pace=None,
        minimum_evidence=3,
    )
    short_endurance = _dimension(
        "short_endurance",
        short_records,
        pace_basis=pace_basis,
        goal_pace=None,
        minimum_evidence=2,
    )
    aerobic_endurance = _dimension(
        "aerobic_endurance",
        aerobic_records,
        pace_basis=pace_basis,
        goal_pace=goal_pace_s_per_100m,
        minimum_evidence=2,
    )
    length_records = tuple(lengths)
    technique = _technique_evidence_dimension(length_records)
    continuous_interval_candidates = tuple(
        item
        for item in comparable
        if (stationary := _decimal_field(item, "stationary_duration_s", "stationary_seconds"))
        is None
        or stationary <= 0
    )
    longest = max(continuous_interval_candidates, key=_distance, default=None)
    longest_distance = _distance(longest) if longest is not None else 0
    evidence_pace = pace_for(longest, basis=pace_basis) if longest is not None else None
    evidence_pace_basis: str | None = pace_basis if evidence_pace is not None else None
    continuity = analyze_continuity(length_records)
    data_quality = assess_data_quality(
        activity,
        intervals=all_intervals,
        lengths=length_records,
    )
    continuous = continuity.longest_continuous_freestyle
    if continuous is not None and continuous.distance_m > longest_distance:
        longest_distance = continuous.distance_m
        evidence_pace = _round(
            continuous.duration_s / Decimal(continuous.distance_m) * Decimal(100)
        )
        evidence_pace_basis = "swim_length"
    readiness_reasons: list[str] = []
    if len(continuous_interval_candidates) < len(comparable):
        readiness_reasons.append("STATIONARY_INTERVAL_EXCLUDED_FROM_CONTINUOUS_READINESS")
    goal_specific_minimum = min(400, goal_distance_m)
    if longest_distance < goal_specific_minimum:
        readiness_reasons.append("NO_GOAL_SPECIFIC_ENDURANCE_EVIDENCE")
        readiness_confidence = QualityLevel.LOW
        ready = None
    elif longest_distance < goal_distance_m:
        readiness_reasons.append("GOAL_DISTANCE_NOT_YET_OBSERVED")
        if longest_distance < 1_000:
            readiness_reasons.append("LIMITED_LONG_DISTANCE_EVIDENCE")
        readiness_confidence = QualityLevel.MEDIUM
        ready = None
    else:
        readiness_confidence = QualityLevel.HIGH
        ready = evidence_pace is not None and evidence_pace <= goal_pace_s_per_100m
    if activity is not None and data_quality.level is QualityLevel.LOW:
        readiness_reasons.append("CANONICAL_DATA_QUALITY_LOW")
        readiness_confidence = QualityLevel.LOW
        ready = None
    elif (
        activity is not None
        and data_quality.level is QualityLevel.MEDIUM
        and readiness_confidence is QualityLevel.HIGH
    ):
        readiness_reasons.append("CANONICAL_DATA_QUALITY_MEDIUM")
        readiness_confidence = QualityLevel.MEDIUM
    readiness = GoalReadiness(
        goal_distance_m=goal_distance_m,
        goal_pace_s_per_100m=goal_pace_s_per_100m,
        longest_evidence_distance_m=longest_distance,
        evidence_pace_s_per_100m=_round(evidence_pace) if evidence_pace is not None else None,
        evidence_pace_basis=evidence_pace_basis,
        pace_gap_s_per_100m=(
            _round(evidence_pace - goal_pace_s_per_100m)
            if evidence_pace is not None and longest_distance >= goal_specific_minimum
            else None
        ),
        ready=ready,
        confidence=readiness_confidence,
        reasons=tuple(readiness_reasons),
    )
    return SpeedEnduranceProfile(
        bands=tuple(bands),
        speed=speed,
        short_endurance=short_endurance,
        aerobic_endurance=aerobic_endurance,
        technique=technique,
        goal_readiness=readiness,
        data_quality=data_quality,
    )


def _node_type(node: object) -> str:
    return _token(_field(node, "type", default="STEP"))


def _planned_interval_type(role: str, stroke: str) -> str:
    if role == "REST":
        return "REST"
    if role == "DRILL" or stroke == "DRILL":
        return "DRILL"
    return "SWIM"


def expand_planned_steps(workout_or_nodes: object) -> tuple[ExpandedPlannedStep, ...]:
    """Expand canonical nested repeats while preserving repeat/set identity."""

    raw_nodes = _field(workout_or_nodes, "nodes", default=workout_or_nodes)
    if not isinstance(raw_nodes, Sequence) or isinstance(raw_nodes, (str, bytes, bytearray)):
        raise ValueError("workout nodes must be a sequence")
    expanded: list[ExpandedPlannedStep] = []

    def walk(
        nodes: Sequence[object],
        *,
        path: str,
        parent_set_id: str | None,
        repetition_index: int | None,
    ) -> None:
        for node_index, node in enumerate(nodes):
            node_path = f"{path}.{node_index}"
            if _node_type(node) == "REPEAT":
                repetitions = _integer(_field(node, "repetitions", default=0)) or 0
                children = _field(node, "children", default=())
                if repetitions <= 0 or not isinstance(children, Sequence):
                    raise ValueError("repeat nodes require positive repetitions and children")
                explicit_id = _field(node, "id", default=None)
                set_id = str(explicit_id) if explicit_id is not None else node_path
                for repetition in range(repetitions):
                    walk(
                        children,
                        path=f"{node_path}.r{repetition}",
                        parent_set_id=set_id,
                        repetition_index=repetition,
                    )
                continue
            role = _role(node)
            stroke = _stroke(_field(node, "stroke", "planned_stroke", default=None))
            end = _field(node, "end_condition", default=node)
            end_type = _token(_field(end, "type", default=None))
            distance = (
                _integer(_field(end, "meters", "distance_m", default=None))
                if end_type == "DISTANCE" or _field(end, "meters", default=None) is not None
                else _integer(_field(node, "distance_m", default=None))
            )
            duration = (
                _decimal(_field(end, "seconds", "duration_s", default=None))
                if end_type == "TIME" or _field(end, "seconds", default=None) is not None
                else _decimal(_field(node, "duration_s", "planned_duration_s", default=None))
            )
            target = _field(node, "target", default=None)
            target_min = _decimal(
                _field(
                    node,
                    "target_min_pace_s_per_100m",
                    default=_field(target, "min_seconds_per_100m", default=None),
                )
            )
            target_max = _decimal(
                _field(
                    node,
                    "target_max_pace_s_per_100m",
                    default=_field(target, "max_seconds_per_100m", default=None),
                )
            )
            raw_id = _field(node, "id", "step_id", default=None)
            intensity = _field(node, "intensity", default=None)
            expanded.append(
                ExpandedPlannedStep(
                    sequence_index=len(expanded),
                    step_id=str(raw_id) if raw_id is not None else None,
                    set_id=parent_set_id,
                    repetition_index=repetition_index,
                    planned_role=role,
                    interval_type=_planned_interval_type(role, stroke),
                    distance_m=distance if distance is not None and distance >= 0 else None,
                    duration_s=duration if duration is not None and duration >= 0 else None,
                    stroke=stroke,
                    intensity=_token(intensity) if intensity is not None else None,
                    target_min_pace_s_per_100m=target_min,
                    target_max_pace_s_per_100m=target_max,
                )
            )

    walk(raw_nodes, path="nodes", parent_set_id=None, repetition_index=None)
    return tuple(expanded)


def _actual_duration(item: object, *, basis: str) -> tuple[Decimal | None, str | None]:
    if basis == "rest":
        # A canonical zero means “no explicit rest identified”, not that a
        # matched planned rest lasted zero seconds.  In that contextual case
        # disclose the timer fallback instead of relabelling it as rest time.
        rest = _decimal_field(item, "rest_duration_s", "rest_seconds")
        if rest is not None and rest > 0:
            return rest, "rest_duration_s"
        timer = _decimal_field(
            item,
            "timer_duration_s",
            "timer_seconds",
            "duration_seconds",
        )
        if timer is not None and timer >= 0:
            return timer, "timer_duration_s"
        return (rest, "rest_duration_s") if rest is not None and rest >= 0 else (None, None)
    fields = {
        "swim": ("swim_duration_s", "swim_seconds"),
        "moving": ("moving_duration_s", "moving_seconds"),
        "timer": ("timer_duration_s", "timer_seconds", "duration_seconds"),
    }
    try:
        names = fields[basis]
    except KeyError as error:
        raise ValueError(f"unsupported duration basis: {basis}") from error
    value = _decimal_field(item, *names)
    return (value, f"{basis}_duration_s") if value is not None and value >= 0 else (None, None)


def _selected_actual_pace(item: object, requested_basis: str) -> tuple[Decimal | None, str | None]:
    if requested_basis != "best_available":
        value = pace_for(item, basis=requested_basis)
        return value, requested_basis if value is not None else None
    for candidate in ("moving", "swim", "timer"):
        value = pace_for(item, basis=candidate)
        if value is not None:
            return value, candidate
    return None, None


def _planned_expected_duration(step: ExpandedPlannedStep) -> Decimal | None:
    """Return only an exact planned duration, never a pace-range midpoint."""

    return step.duration_s


def _planned_duration_range(
    step: ExpandedPlannedStep,
) -> tuple[Decimal | None, Decimal | None]:
    if (
        step.distance_m is None
        or step.target_min_pace_s_per_100m is None
        or step.target_max_pace_s_per_100m is None
    ):
        return None, None
    distance_factor = Decimal(step.distance_m) / Decimal(100)
    return (
        _round(step.target_min_pace_s_per_100m * distance_factor),
        _round(step.target_max_pace_s_per_100m * distance_factor),
    )


def _compatibility(step: ExpandedPlannedStep, actual: object) -> Decimal:
    actual_type = _interval_type(actual)
    if step.interval_type == actual_type:
        type_score = _ONE
    elif step.interval_type == "SWIM" and actual_type == "UNKNOWN" and _distance(actual) > 0:
        type_score = Decimal("0.5")
    elif step.interval_type == "REST" and actual_type == "UNKNOWN" and _distance(actual) == 0:
        type_score = Decimal("0.5")
    elif step.interval_type == "DRILL" and actual_type == "SWIM" and _distance(actual) > 0:
        # Garmin commonly records a planned drill as an ordinary swim interval.
        # This remains weaker than an exact type match; distance and ordered
        # sequence must still carry enough evidence to pass the match threshold.
        type_score = Decimal("0.75")
    else:
        type_score = _ZERO
    if step.distance_m is not None:
        actual_distance = _distance(actual)
        if step.distance_m == 0:
            amount_score = _ONE if actual_distance == 0 else _ZERO
        else:
            relative_error = Decimal(abs(actual_distance - step.distance_m)) / Decimal(
                step.distance_m
            )
            amount_score = max(_ZERO, _ONE - relative_error)
    elif step.duration_s is not None:
        actual_duration, _ = _actual_duration(
            actual,
            basis="rest" if step.interval_type == "REST" else "timer",
        )
        if actual_duration is None or step.duration_s == 0:
            amount_score = _ZERO
        else:
            relative_error = abs(actual_duration - step.duration_s) / step.duration_s
            amount_score = max(_ZERO, _ONE - relative_error)
    else:
        amount_score = Decimal("0.5")
    actual_stroke = _stroke(actual)
    if step.interval_type == "REST":
        stroke_score = _ONE
    elif step.stroke in _INDETERMINATE_STROKES or actual_stroke in _INDETERMINATE_STROKES:
        stroke_score = Decimal("0.5")
    else:
        stroke_score = _ONE if step.stroke == actual_stroke else _ZERO
    return _round(
        type_score * Decimal("0.45")
        + amount_score * Decimal("0.40")
        + stroke_score * Decimal("0.15"),
        _FOUR_PLACES,
    )


def _ordered_matches(
    steps: Sequence[ExpandedPlannedStep],
    actual: Sequence[object],
    *,
    minimum_match_score: Decimal,
) -> dict[int, tuple[int, Decimal]]:
    rows = len(steps) + 1
    columns = len(actual) + 1
    scores = [[_ZERO for _ in range(columns)] for _ in range(rows)]
    counts = [[0 for _ in range(columns)] for _ in range(rows)]
    choices = [["" for _ in range(columns)] for _ in range(rows)]
    for row in range(1, rows):
        choices[row][0] = "SKIP_PLANNED"
    for column in range(1, columns):
        choices[0][column] = "SKIP_ACTUAL"
    for row in range(1, rows):
        for column in range(1, columns):
            candidates: list[tuple[Decimal, int, int, str]] = [
                (scores[row - 1][column], counts[row - 1][column], 0, "SKIP_PLANNED"),
                (scores[row][column - 1], counts[row][column - 1], 1, "SKIP_ACTUAL"),
            ]
            match_score = _compatibility(steps[row - 1], actual[column - 1])
            if match_score >= minimum_match_score:
                candidates.append(
                    (
                        scores[row - 1][column - 1] + match_score,
                        counts[row - 1][column - 1] + 1,
                        2,
                        "MATCH",
                    )
                )
            score, count, _, choice = max(candidates, key=lambda item: (item[0], item[1], item[2]))
            scores[row][column] = score
            counts[row][column] = count
            choices[row][column] = choice
    matches: dict[int, tuple[int, Decimal]] = {}
    row = len(steps)
    column = len(actual)
    while row > 0 or column > 0:
        choice = choices[row][column]
        if choice == "MATCH":
            matches[row - 1] = (
                column - 1,
                _compatibility(steps[row - 1], actual[column - 1]),
            )
            row -= 1
            column -= 1
        elif choice == "SKIP_PLANNED":
            row -= 1
        elif choice == "SKIP_ACTUAL":
            column -= 1
        else:
            break
    return matches


def _assess_adherence_quality(
    alignments: Sequence[StepAlignment],
    *,
    has_unmatched_actual: bool,
) -> QualityAssessment:
    """Assess planned/actual evidence without unrelated activity-quality checks."""

    if not alignments:
        return QualityAssessment(QualityLevel.LOW, ("NO_PLANNED_STEPS",))
    reasons: list[str] = []
    unmatched_planned = sum(
        alignment.status is AlignmentStatus.UNMATCHED for alignment in alignments
    )
    partial = sum(alignment.status is AlignmentStatus.PARTIAL for alignment in alignments)
    if unmatched_planned:
        reasons.append("WORKOUT_STEP_UNMATCHED")
    if partial:
        reasons.append("WORKOUT_STEP_PARTIAL")
    if has_unmatched_actual:
        reasons.append("UNMATCHED_ACTUAL_INTERVALS")
    semantic_reasons = {
        reason
        for alignment in alignments
        for reason in alignment.reasons
        if reason
        in {
            "PLANNED_PACE_BASIS_INFERRED_SWIM",
            "TARGET_SWIM_PACE_UNAVAILABLE",
        }
    }
    reasons.extend(sorted(semantic_reasons))
    matched = len(alignments) - unmatched_planned
    if matched == 0 or unmatched_planned * 2 > len(alignments):
        level = QualityLevel.LOW
    elif reasons:
        level = QualityLevel.MEDIUM
    else:
        level = QualityLevel.HIGH
    return QualityAssessment(level, tuple(reasons))


def align_planned_steps(
    planned_workout_or_steps: object,
    actual_intervals: Iterable[object],
    *,
    pace_basis: str = "moving",
    minimum_match_score: Decimal = Decimal("0.60"),
) -> WorkoutAdherence:
    """Order-align expanded planned steps and actual intervals, then compute adherence."""

    if not _ZERO < minimum_match_score <= _ONE:
        raise ValueError("minimum match score must be in (0, 1]")
    if (
        isinstance(planned_workout_or_steps, Sequence)
        and not isinstance(planned_workout_or_steps, (str, bytes, bytearray))
        and all(isinstance(item, ExpandedPlannedStep) for item in planned_workout_or_steps)
    ):
        steps = tuple(planned_workout_or_steps)
    else:
        steps = expand_planned_steps(planned_workout_or_steps)
    actual = tuple(actual_intervals)
    matches = _ordered_matches(steps, actual, minimum_match_score=minimum_match_score)
    used_actual = {actual_index for actual_index, _ in matches.values()}
    alignments: list[StepAlignment] = []
    for planned_index, step in enumerate(steps):
        planned_duration_min, planned_duration_max = _planned_duration_range(step)
        has_pace_target = (
            step.target_min_pace_s_per_100m is not None
            and step.target_max_pace_s_per_100m is not None
        )
        match = matches.get(planned_index)
        if match is None:
            alignments.append(
                StepAlignment(
                    planned_index=planned_index,
                    actual_index=None,
                    set_id=step.set_id,
                    repetition_index=step.repetition_index,
                    status=AlignmentStatus.UNMATCHED,
                    confidence=_ZERO,
                    planned_role=step.planned_role,
                    planned_interval_type=step.interval_type,
                    actual_interval_type=None,
                    planned_distance_m=step.distance_m,
                    actual_distance_m=None,
                    distance_difference_m=None,
                    planned_duration_s=_planned_expected_duration(step),
                    planned_duration_min_s=planned_duration_min,
                    planned_duration_max_s=planned_duration_max,
                    actual_duration_s=None,
                    actual_duration_basis=None,
                    duration_difference_s=None,
                    duration_target_met=None,
                    planned_pace_s_per_100m=(
                        _round(
                            (step.target_min_pace_s_per_100m + step.target_max_pace_s_per_100m)
                            / Decimal(2)
                        )
                        if step.target_min_pace_s_per_100m is not None
                        and step.target_max_pace_s_per_100m is not None
                        else None
                    ),
                    planned_pace_min_s_per_100m=step.target_min_pace_s_per_100m,
                    planned_pace_max_s_per_100m=step.target_max_pace_s_per_100m,
                    planned_pace_basis="swim" if has_pace_target else None,
                    actual_pace_s_per_100m=None,
                    actual_pace_basis=None,
                    pace_difference_s_per_100m=None,
                    target_pace_met=None,
                    planned_stroke=step.stroke,
                    actual_stroke=None,
                    stroke_match=None,
                    planned_intensity=step.intensity,
                    adherence_ratio=_ZERO,
                    reasons=("PLANNED_STEP_UNMATCHED",),
                )
            )
            continue
        actual_index, confidence = match
        item = actual[actual_index]
        actual_distance = _distance(item)
        planned_duration = _planned_expected_duration(step)
        duration_basis = (
            "rest"
            if step.interval_type == "REST"
            else "timer"
            if planned_duration is not None or not has_pace_target
            else "swim"
        )
        actual_duration, actual_duration_basis = _actual_duration(item, basis=duration_basis)
        actual_stroke = _stroke(item)
        distance_difference = (
            actual_distance - step.distance_m if step.distance_m is not None else None
        )
        duration_difference = (
            _round(actual_duration - planned_duration)
            if actual_duration is not None and planned_duration is not None
            else None
        )
        duration_target_met = (
            planned_duration_min <= actual_duration <= planned_duration_max
            if actual_duration is not None
            and planned_duration is None
            and planned_duration_min is not None
            and planned_duration_max is not None
            else None
        )
        if step.distance_m is not None and step.distance_m > 0:
            adherence = _round(Decimal(actual_distance) / Decimal(step.distance_m), _FOUR_PLACES)
        elif planned_duration is not None and planned_duration > 0 and actual_duration is not None:
            adherence = _round(actual_duration / planned_duration, _FOUR_PLACES)
        else:
            adherence = None
        reasons: list[str] = []
        if step.interval_type != _interval_type(item):
            reasons.append("INTERVAL_TYPE_MISMATCH")
        if distance_difference not in {None, 0}:
            reasons.append("DISTANCE_MISMATCH")
        if duration_difference is not None and abs(duration_difference) > Decimal("1"):
            reasons.append("DURATION_MISMATCH")
        if duration_target_met is False:
            reasons.append("DURATION_TARGET_MISSED")
        stroke_match = None
        if step.interval_type != "REST" and step.stroke not in {"UNKNOWN", "CHOICE", "MIXED"}:
            if actual_stroke in _INDETERMINATE_STROKES:
                reasons.append("STROKE_DETECTION_INDETERMINATE")
            else:
                stroke_match = actual_stroke == step.stroke
            if stroke_match is False:
                reasons.append("STROKE_MISMATCH")
        status = (
            AlignmentStatus.MATCHED if confidence >= Decimal("0.85") else AlignmentStatus.PARTIAL
        )
        planned_pace = (
            _round((step.target_min_pace_s_per_100m + step.target_max_pace_s_per_100m) / Decimal(2))
            if step.target_min_pace_s_per_100m is not None
            and step.target_max_pace_s_per_100m is not None
            else None
        )
        actual_pace, actual_pace_basis = _selected_actual_pace(
            item,
            "swim" if has_pace_target else pace_basis,
        )
        pace_difference = (
            _round(actual_pace - planned_pace)
            if actual_pace is not None and planned_pace is not None
            else None
        )
        target_pace_met = (
            step.target_min_pace_s_per_100m <= actual_pace <= step.target_max_pace_s_per_100m
            if actual_pace is not None
            and step.target_min_pace_s_per_100m is not None
            and step.target_max_pace_s_per_100m is not None
            else None
        )
        if target_pace_met is False:
            reasons.append("PACE_TARGET_MISSED")
        if has_pace_target:
            reasons.append("PLANNED_PACE_BASIS_INFERRED_SWIM")
            if actual_pace is None:
                reasons.append("TARGET_SWIM_PACE_UNAVAILABLE")
        alignments.append(
            StepAlignment(
                planned_index=planned_index,
                actual_index=_index(item, actual_index),
                set_id=step.set_id,
                repetition_index=step.repetition_index,
                status=status,
                confidence=confidence,
                planned_role=step.planned_role,
                planned_interval_type=step.interval_type,
                actual_interval_type=_interval_type(item),
                planned_distance_m=step.distance_m,
                actual_distance_m=actual_distance,
                distance_difference_m=distance_difference,
                planned_duration_s=planned_duration,
                planned_duration_min_s=planned_duration_min,
                planned_duration_max_s=planned_duration_max,
                actual_duration_s=actual_duration,
                actual_duration_basis=actual_duration_basis,
                duration_difference_s=duration_difference,
                duration_target_met=duration_target_met,
                planned_pace_s_per_100m=planned_pace,
                planned_pace_min_s_per_100m=step.target_min_pace_s_per_100m,
                planned_pace_max_s_per_100m=step.target_max_pace_s_per_100m,
                planned_pace_basis="swim" if has_pace_target else None,
                actual_pace_s_per_100m=actual_pace,
                actual_pace_basis=actual_pace_basis,
                pace_difference_s_per_100m=pace_difference,
                target_pace_met=target_pace_met,
                planned_stroke=step.stroke,
                actual_stroke=actual_stroke,
                stroke_match=stroke_match,
                planned_intensity=step.intensity,
                adherence_ratio=adherence,
                reasons=tuple(reasons),
            )
        )
    planned_distance = sum(step.distance_m or 0 for step in steps)
    actual_distance = sum(_distance(item) for item in actual)
    ratio = (
        _round(Decimal(actual_distance) / Decimal(planned_distance), _FOUR_PLACES)
        if planned_distance > 0
        else None
    )
    matched = sum(alignment.status is not AlignmentStatus.UNMATCHED for alignment in alignments)
    matched_ratio = _round(Decimal(matched) / Decimal(len(steps)), _FOUR_PLACES) if steps else None
    confidences = tuple(
        alignment.confidence
        for alignment in alignments
        if alignment.status is not AlignmentStatus.UNMATCHED
    )
    mean_confidence = _round(_mean(confidences), _FOUR_PLACES) if confidences else None
    quality = _assess_adherence_quality(
        alignments,
        has_unmatched_actual=len(used_actual) != len(actual),
    )
    return WorkoutAdherence(
        alignments=tuple(alignments),
        unmatched_actual_indices=tuple(
            _index(item, index) for index, item in enumerate(actual) if index not in used_actual
        ),
        planned_distance_m=planned_distance,
        actual_distance_m=actual_distance,
        distance_difference_m=actual_distance - planned_distance,
        distance_adherence_ratio=ratio,
        matched_step_ratio=matched_ratio,
        mean_alignment_confidence=mean_confidence,
        quality=quality,
    )


__all__ = [
    "AlignmentStatus",
    "ContinuityAnalysis",
    "ContinuousBlock",
    "DimensionProfile",
    "DistanceBandProfile",
    "EquivalentSetAnalysis",
    "EquivalentSetKey",
    "ExpandedPlannedStep",
    "GoalReadiness",
    "OutlierFlag",
    "QualityAssessment",
    "QualityLevel",
    "SpeedEnduranceProfile",
    "StepAlignment",
    "TrendDirection",
    "WindowPerformance",
    "WorkoutAdherence",
    "align_planned_steps",
    "analyze_continuity",
    "assess_data_quality",
    "build_speed_endurance_profile",
    "detect_interval_outliers",
    "expand_planned_steps",
    "format_seconds_mmss",
    "freestyle_work_intervals",
    "group_equivalent_sets",
    "pace_for",
]
