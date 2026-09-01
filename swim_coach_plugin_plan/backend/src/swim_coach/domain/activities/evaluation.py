"""Resolve post-session evaluation facts without losing their provenance."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from swim_coach.domain.activities.entities import ActivityNormalization, SessionFeedback


class SessionEvaluationSource(StrEnum):
    GARMIN = "GARMIN"
    MANUAL_OVERRIDE = "MANUAL_OVERRIDE"


@dataclass(frozen=True, slots=True)
class SessionEvaluation:
    garmin_rpe: Decimal | None
    garmin_feeling_score: int | None
    manual_rpe: int | None
    manual_feeling_score: int | None
    effective_rpe: Decimal | None
    effective_feeling_score: int | None
    rpe_source: SessionEvaluationSource | None
    feeling_score_source: SessionEvaluationSource | None


def resolve_session_evaluation(
    normalization: ActivityNormalization | None,
    feedback: SessionFeedback | None,
) -> SessionEvaluation:
    """Apply field-level manual-over-Garmin precedence.

    A manual record may intentionally omit RPE when Garmin already supplied it;
    ratings such as technique and pain therefore never become implicit RPE
    overrides.
    """

    garmin_rpe = normalization.perceived_effort_rpe if normalization is not None else None
    garmin_feeling = normalization.feeling_score if normalization is not None else None
    manual_rpe = feedback.rpe if feedback is not None else None
    manual_feeling = feedback.feeling_score if feedback is not None else None
    effective_rpe = Decimal(manual_rpe) if manual_rpe is not None else garmin_rpe
    effective_feeling = manual_feeling if manual_feeling is not None else garmin_feeling
    return SessionEvaluation(
        garmin_rpe=garmin_rpe,
        garmin_feeling_score=garmin_feeling,
        manual_rpe=manual_rpe,
        manual_feeling_score=manual_feeling,
        effective_rpe=effective_rpe,
        effective_feeling_score=effective_feeling,
        rpe_source=(
            SessionEvaluationSource.MANUAL_OVERRIDE
            if manual_rpe is not None
            else SessionEvaluationSource.GARMIN
            if garmin_rpe is not None
            else None
        ),
        feeling_score_source=(
            SessionEvaluationSource.MANUAL_OVERRIDE
            if manual_feeling is not None
            else SessionEvaluationSource.GARMIN
            if garmin_feeling is not None
            else None
        ),
    )
