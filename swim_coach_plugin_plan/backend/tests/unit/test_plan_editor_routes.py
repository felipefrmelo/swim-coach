"""The auxiliary editor stages first and applies only the exact approved proposal."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from test_training_plan_validator import plan_definition

from swim_coach.domain.planning import TrainingPlanRevisionDefinition
from swim_coach.domain.shared.value_objects import CorrelationId, EntityId, UserId
from swim_coach.interfaces.rest.coaching import (
    PlanApplyRequest,
    PlanEditRequest,
    apply_plan_edit,
    propose_plan_edit,
)


@pytest.mark.asyncio
async def test_editor_proposal_does_not_apply_or_publish() -> None:
    pid = uuid4()
    uid = UserId.new()
    proposal = SimpleNamespace(
        id=EntityId.new(),
        action_hash="a" * 64,
        expires_at=datetime.now(UTC),
        impact={"diff": {"changed_weeks": [1]}},
    )
    coach = SimpleNamespace(
        propose_plan_revision=AsyncMock(return_value=SimpleNamespace(proposal=proposal)),
        apply_plan_revision=AsyncMock(),
    )
    result = await propose_plan_edit(
        pid,
        PlanEditRequest(
            expected_revision=9, definition=plan_definition(), rationale="Adjust next session"
        ),
        SimpleNamespace(user=SimpleNamespace(id=uid)),
        SimpleNamespace(coach_commands=coach),
        CorrelationId.new(),
    )
    assert result["expected_revision"] == 9
    assert result["action_hash"] == proposal.action_hash
    assert result["proposal_id"] == str(proposal.id)
    coach.apply_plan_revision.assert_not_called()
    args = coach.propose_plan_revision.call_args.kwargs
    assert args["plan_id"] == EntityId(pid)
    assert args["revision_definition"].kind == "MANUAL_EDIT"
    assert args["revision_definition"].review_id is None
    assert coach.propose_plan_revision.call_args.args == (uid,)


@pytest.mark.asyncio
async def test_editor_apply_passes_exact_hash_and_expected_revision() -> None:
    coach = SimpleNamespace(
        apply_plan_revision=AsyncMock(
            return_value=SimpleNamespace(
                plan=SimpleNamespace(current_revision=10), materialization_job_ids=()
            )
        )
    )
    payload = PlanApplyRequest(proposal_id=uuid4(), expected_revision=9, approval_hash="b" * 64)
    uid = UserId.new()
    result = await apply_plan_edit(
        uuid4(),
        payload,
        SimpleNamespace(user=SimpleNamespace(id=uid)),
        SimpleNamespace(coach_commands=coach),
        CorrelationId.new(),
    )
    assert result["garmin_changed"] is False
    assert coach.apply_plan_revision.call_args.kwargs["approval_hash"] == "b" * 64
    assert coach.apply_plan_revision.call_args.kwargs["expected_revision"] == 9
    assert coach.apply_plan_revision.call_args.args == (uid,)


def test_manual_edits_cannot_smuggle_adaptation_decisions() -> None:
    with pytest.raises(ValueError):
        TrainingPlanRevisionDefinition(
            kind="MANUAL_EDIT",
            rationale="Edit",
            definition=plan_definition(),
            review_id=str(uuid4()),
            decision="PROGRESS",
        )
