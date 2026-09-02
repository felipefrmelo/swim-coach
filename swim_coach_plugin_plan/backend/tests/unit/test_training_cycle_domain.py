from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from swim_coach.domain.planning import (
    EvidenceConfidence,
    PlanDecision,
    PlanDetailLevel,
    PlanPhase,
    PlanReview,
    PlanSessionIntent,
    PlanStatus,
    PlanWeek,
    TrainingPlan,
    TrainingPlanDocument,
    TrainingPlanRevision,
    canonical_json_hash,
    plan_document_diff,
)
from swim_coach.domain.shared.errors import DomainError
from swim_coach.domain.shared.value_objects import EntityId, UserId


def workout() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "title": "Técnica 800 m",
        "sport": "POOL_SWIMMING",
        "pool_length_m": 20,
        "purpose": "TECHNIQUE",
        "tags": [],
        "nodes": [
            {
                "type": "step",
                "step_role": "WORK",
                "end_condition": {"type": "distance", "meters": 800},
                "target": {"type": "none"},
                "stroke": {"type": "freestyle"},
                "equipment": [],
            }
        ],
    }


def document(*, session_id: EntityId | None = None) -> TrainingPlanDocument:
    selected_id = session_id or EntityId.new()
    weeks = [
        PlanWeek(
            week_number=1,
            focus="Técnica",
            detail_level=PlanDetailLevel.DETAILED,
            target_distance_min_m=800,
            target_distance_max_m=800,
            target_duration_min_minutes=20,
            target_duration_max_minutes=45,
            session_count=1,
            load_target="BASE",
            success_criteria=("Técnica controlada",),
            sessions=(
                PlanSessionIntent(
                    session_intent_id=str(selected_id),
                    session_number=1,
                    purpose="technique",
                    target_distance_m=800,
                    max_duration_minutes=45,
                    intensity="EASY",
                    scheduled_date=date(2026, 9, 7),
                    key_set="8 x 100 m",
                    workout=workout(),
                ),
            ),
        )
    ]
    weeks.extend(
        PlanWeek(
            week_number=number,
            focus="Endurance",
            detail_level=(PlanDetailLevel.OUTLINE if number == 2 else PlanDetailLevel.STRATEGIC),
            target_distance_min_m=800,
            target_distance_max_m=1000,
            target_duration_min_minutes=20,
            target_duration_max_minutes=45,
            session_count=1,
            load_target="BUILD",
        )
        for number in range(2, 5)
    )
    return TrainingPlanDocument(
        strategy_summary="Construir endurance sem prometer a meta ao fim do ciclo.",
        duration_weeks=4,
        baseline_snapshot={"longest_continuous_m": 120},
        baseline_confidence=EvidenceConfidence.LOW,
        phases=(
            PlanPhase(
                name="Base",
                start_week=1,
                end_week=3,
                focus="Técnica e endurance",
            ),
            PlanPhase(
                name="Checkpoint",
                start_week=4,
                end_week=4,
                focus="Teste de prontidão",
            ),
        ),
        weeks=tuple(weeks),
        ruleset_version="1.1.0",
        ruleset_hash="a" * 64,
    )


def test_plan_document_is_hashed_and_revision_history_is_append_only() -> None:
    first = document()
    now = datetime(2026, 9, 1, tzinfo=UTC)
    plan = TrainingPlan(
        id=EntityId.new(),
        user_id=UserId.new(),
        goal_id=EntityId.new(),
        title="Ciclo 2 km",
        start_date=date(2026, 9, 7),
        end_date=date(2026, 9, 7) + timedelta(days=27),
        duration_weeks=4,
        created_at=now,
        updated_at=now,
    )
    revision = TrainingPlanRevision(
        id=EntityId.new(),
        plan_id=plan.id,
        revision_number=1,
        document=first,
        content_hash=first.content_hash,
        reason="Criação",
        diff=plan_document_diff(None, first),
        created_at=now,
    )

    plan.apply_revision(revision, now)

    assert plan.status is PlanStatus.ACTIVE
    assert plan.current_revision == 1
    assert revision.diff["type"] == "CREATE"


def test_stale_revision_and_invalid_status_transition_are_rejected() -> None:
    now = datetime(2026, 9, 1, tzinfo=UTC)
    plan = TrainingPlan(
        id=EntityId.new(),
        user_id=UserId.new(),
        goal_id=EntityId.new(),
        title="Ciclo",
        start_date=date(2026, 9, 7),
        end_date=date(2026, 10, 4),
        duration_weeks=4,
        created_at=now,
        updated_at=now,
    )
    first = document()
    stale = TrainingPlanRevision(
        id=EntityId.new(),
        plan_id=plan.id,
        revision_number=2,
        previous_revision_id=EntityId.new(),
        document=first,
        content_hash=first.content_hash,
        reason="Stale",
    )

    with pytest.raises(DomainError, match="stale"):
        plan.apply_revision(stale, now)
    with pytest.raises(DomainError, match="transition"):
        plan.set_status(PlanStatus.PAUSED, now)


def test_review_records_one_explicit_recommendation() -> None:
    evidence = {"completed_sessions": 2, "pain_signals": []}
    review = PlanReview(
        id=EntityId.new(),
        user_id=UserId.new(),
        plan_id=EntityId.new(),
        plan_revision=1,
        week_number=1,
        evidence_snapshot=evidence,
        evidence_hash=canonical_json_hash(evidence),
        confidence_cap=EvidenceConfidence.MEDIUM,
        eligible=True,
        eligibility_reason="ALL_SESSIONS_RESOLVED",
    )

    recommended = review.with_recommendation(
        decision=PlanDecision.HOLD,
        rationale="Consolidar o estímulo por mais uma semana.",
        recommendation={"diff": {"changed_weeks": [2]}},
        proposal_id=EntityId.new(),
    )

    assert recommended.decision is PlanDecision.HOLD
    assert recommended.proposal_id is not None
    with pytest.raises(DomainError, match="already has"):
        recommended.with_recommendation(
            decision=PlanDecision.PROGRESS,
            rationale="Tentar substituir a decisão existente.",
            recommendation={},
            proposal_id=EntityId.new(),
        )
