"""Normalized swimming activity, analysis, matching and feedback domain."""

from swim_coach.domain.activities.entities import (
    ActivityAnalysis,
    ActivityInterval,
    ActivityLap,
    ActivityLength,
    ActivityNormalization,
    DataQuality,
    FileArtifact,
    IntervalType,
    LengthType,
    NormalizedActivity,
    PlannedRole,
    ProvenanceSource,
    SessionFeedback,
    WorkoutExecutionMatch,
)
from swim_coach.domain.activities.evaluation import (
    SessionEvaluation,
    SessionEvaluationSource,
    resolve_session_evaluation,
)
from swim_coach.domain.activities.metrics import (
    analyze_swim,
    coefficient_of_variation,
    completion_ratio,
    fade_percent,
    pace_seconds_per_100m,
    srpe_load,
)

__all__ = [
    "ActivityAnalysis",
    "ActivityInterval",
    "ActivityLap",
    "ActivityLength",
    "ActivityNormalization",
    "DataQuality",
    "FileArtifact",
    "IntervalType",
    "LengthType",
    "NormalizedActivity",
    "PlannedRole",
    "ProvenanceSource",
    "SessionEvaluation",
    "SessionEvaluationSource",
    "SessionFeedback",
    "WorkoutExecutionMatch",
    "analyze_swim",
    "coefficient_of_variation",
    "completion_ratio",
    "fade_percent",
    "pace_seconds_per_100m",
    "resolve_session_evaluation",
    "srpe_load",
]
