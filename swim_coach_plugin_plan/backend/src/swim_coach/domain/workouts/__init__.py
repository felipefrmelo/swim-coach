"""Canonical workout authoring domain."""

from swim_coach.domain.workouts.entities import (
    PlannedWorkout,
    PlannedWorkoutStatus,
    WorkoutRevision,
    WorkoutSchedule,
    WorkoutTemplate,
)
from swim_coach.domain.workouts.schema import (
    CanonicalWorkout,
    DistanceEnd,
    PaceTarget,
    RepeatNode,
    StandardStroke,
    StepNode,
    ValidationIssue,
    WorkoutTotals,
    WorkoutValidationResult,
    canonical_content_hash,
    validate_workout,
)

__all__ = [
    "CanonicalWorkout",
    "DistanceEnd",
    "PaceTarget",
    "PlannedWorkout",
    "PlannedWorkoutStatus",
    "RepeatNode",
    "StandardStroke",
    "StepNode",
    "ValidationIssue",
    "WorkoutRevision",
    "WorkoutSchedule",
    "WorkoutTemplate",
    "WorkoutTotals",
    "WorkoutValidationResult",
    "canonical_content_hash",
    "validate_workout",
]
