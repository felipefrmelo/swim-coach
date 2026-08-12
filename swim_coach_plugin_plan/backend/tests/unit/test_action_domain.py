"""P07 action approval invariants."""

from datetime import UTC, datetime, timedelta

import pytest

from swim_coach.domain.actions import (
    ActionProposal,
    ActionProposalStatus,
    canonical_action_hash,
)
from swim_coach.domain.shared.errors import DomainError, DomainValidationError
from swim_coach.domain.shared.value_objects import EntityId, UserId


def proposal(*, lifetime: timedelta = timedelta(minutes=15)) -> ActionProposal:
    now = datetime(2026, 8, 11, 20, tzinfo=UTC)
    return ActionProposal.ready_for_review(
        id=EntityId.new(),
        user_id=UserId.new(),
        action_type="garmin.publish_and_schedule.v1",
        target_type="planned_workout",
        target_id=EntityId.new(),
        target_revision_id=EntityId.new(),
        payload={"compiled_hash": "a" * 64, "scheduled_date": "2026-08-12"},
        impact={"distance_m": 1600, "external_effects": ["publish", "schedule"]},
        expires_at=now + lifetime,
        created_at=now,
    )


def test_canonical_hash_ignores_json_key_order_but_detects_tamper() -> None:
    item = proposal()
    reordered_payload = {"scheduled_date": "2026-08-12", "compiled_hash": "a" * 64}
    same = canonical_action_hash(
        action_type=item.action_type,
        target_type=item.target_type,
        target_id=item.target_id,
        target_revision_id=item.target_revision_id,
        payload=reordered_payload,
        impact=item.impact,
    )
    assert same == item.action_hash
    tampered = {**reordered_payload, "scheduled_date": "2026-08-13"}
    assert (
        canonical_action_hash(
            action_type=item.action_type,
            target_type=item.target_type,
            target_id=item.target_id,
            target_revision_id=item.target_revision_id,
            payload=tampered,
            impact=item.impact,
        )
        != item.action_hash
    )


def test_constructor_rejects_payload_tamper() -> None:
    item = proposal()
    item.payload["scheduled_date"] = "2026-08-13"
    with pytest.raises(DomainValidationError):
        ActionProposal(
            id=item.id,
            user_id=item.user_id,
            action_type=item.action_type,
            target_type=item.target_type,
            target_id=item.target_id,
            target_revision_id=item.target_revision_id,
            payload=item.payload,
            impact=item.impact,
            action_hash=item.action_hash,
            expires_at=item.expires_at,
            created_at=item.created_at,
        )


def test_approval_requires_exact_hash_and_cannot_be_replayed() -> None:
    item = proposal()
    now = item.created_at + timedelta(minutes=1)
    with pytest.raises(DomainError, match="no longer matches") as error:
        item.approve(action_hash="0" * 64, now=now)
    assert error.value.code == "ACTION_TAMPERED"
    item.approve(action_hash=item.action_hash, now=now)
    assert item.status is ActionProposalStatus.APPROVED
    with pytest.raises(DomainError) as replay:
        item.approve(action_hash=item.action_hash, now=now)
    assert replay.value.code == "ACTION_NOT_REVIEWABLE"


def test_expired_proposal_cannot_be_approved_or_queued() -> None:
    item = proposal(lifetime=timedelta(seconds=1))
    with pytest.raises(DomainError) as error:
        item.approve(action_hash=item.action_hash, now=item.expires_at)
    assert error.value.code == "ACTION_EXPIRED"
    assert item.status is ActionProposalStatus.EXPIRED


def test_execution_state_distinguishes_ambiguous_outcome() -> None:
    item = proposal()
    now = item.created_at + timedelta(minutes=1)
    item.approve(action_hash=item.action_hash, now=now)
    item.queue(now)
    item.start(now)
    item.fail(now, ambiguous=True)
    assert item.status is ActionProposalStatus.NEEDS_RECONCILIATION
