import pytest

from swim_coach.application.services.training_cycles import TrainingCycleService
from swim_coach.domain.planning import (
    EvidenceConfidence,
    PlanDecision,
    PlanReview,
    canonical_json_hash,
)
from swim_coach.domain.shared.errors import DomainError
from swim_coach.domain.shared.value_objects import EntityId, UserId


def review(*, confidence: EvidenceConfidence, comparable: int, pain: bool = False) -> PlanReview:
    evidence = {
        "comparable_evidence_count": comparable,
        "pain_signals": ([{"intensity": 3}] if pain else []),
        "notes": [],
    }
    return PlanReview(
        id=EntityId.new(),
        user_id=UserId.new(),
        plan_id=EntityId.new(),
        plan_revision=1,
        week_number=1,
        evidence_snapshot=evidence,
        evidence_hash=canonical_json_hash(evidence),
        confidence_cap=confidence,
        eligible=True,
        eligibility_reason="ALL_SESSIONS_RESOLVED",
    )


@pytest.mark.parametrize(
    ("candidate", "expected_code"),
    [
        (
            review(confidence=EvidenceConfidence.HIGH, comparable=3, pain=True),
            "PLAN_PROGRESS_BLOCKED_BY_PAIN",
        ),
        (
            review(confidence=EvidenceConfidence.LOW, comparable=3),
            "PLAN_PROGRESS_LOW_CONFIDENCE",
        ),
        (
            review(confidence=EvidenceConfidence.HIGH, comparable=1),
            "PLAN_PROGRESS_EVIDENCE_REQUIRED",
        ),
    ],
)
def test_progression_requires_safe_repeated_evidence(
    candidate: PlanReview, expected_code: str
) -> None:
    with pytest.raises(DomainError) as captured:
        TrainingCycleService._validate_decision(candidate, PlanDecision.PROGRESS)

    assert captured.value.code == expected_code


def test_progression_accepts_two_comparable_samples_without_pain() -> None:
    candidate = review(confidence=EvidenceConfidence.MEDIUM, comparable=2)

    TrainingCycleService._validate_decision(candidate, PlanDecision.PROGRESS)
