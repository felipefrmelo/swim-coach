from test_training_cycle_domain import document

from swim_coach.domain.planning import (
    EvidenceConfidence,
    PlanDecision,
    PlanReview,
    TrainingPlanRevisionDefinition,
    canonical_json_hash,
)
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


def test_backend_records_but_does_not_choose_adaptation_decision() -> None:
    evidence = review(confidence=EvidenceConfidence.LOW, comparable=0, pain=True)

    revision = TrainingPlanRevisionDefinition(
        kind="ADAPTATION",
        review_id=str(evidence.id),
        decision=PlanDecision.PROGRESS,
        rationale="Coach accepts responsibility for the explicit decision.",
        definition=document(),
    )

    assert revision.decision is PlanDecision.PROGRESS
