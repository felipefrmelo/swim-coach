"""Normalized swimming activity, analysis, matching and feedback domain."""

from swim_coach.domain.activities.entities import (
    ActivityAnalysis,
    ActivityInterval,
    ActivityLap,
    ActivityLength,
    ActivityNormalization,
    DataQuality,
    FileArtifact,
    NormalizedActivity,
    SessionFeedback,
    WorkoutExecutionMatch,
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
    "NormalizedActivity",
    "SessionFeedback",
    "WorkoutExecutionMatch",
    "analyze_swim",
    "coefficient_of_variation",
    "completion_ratio",
    "fade_percent",
    "pace_seconds_per_100m",
    "srpe_load",
]
