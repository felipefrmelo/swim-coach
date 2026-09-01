from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from swim_coach.domain.activities import ActivityInterval, ActivityLength
from swim_coach.domain.shared.errors import DomainValidationError
from swim_coach.domain.shared.value_objects import EntityId
from swim_coach.infrastructure.db.uow import (
    _legacy_child_provenance,
    _normalization,
)


def test_legacy_length_aliases_do_not_materialize_canonical_duration_facts() -> None:
    normalization_id = EntityId.new()
    interval_id = EntityId.new()

    length = ActivityLength(
        id=EntityId.new(),
        normalization_id=normalization_id,
        interval_id=interval_id,
        length_index=0,
        distance_m=20,
        duration_seconds=Decimal("30"),
        stroke_type="freestyle",
    )
    interval = ActivityInterval(
        id=interval_id,
        normalization_id=normalization_id,
        interval_index=0,
        interval_type="work",
        start_offset_seconds=Decimal(0),
        duration_seconds=Decimal("30"),
        rest_seconds=Decimal("5"),
        distance_m=20,
    )

    assert length.elapsed_seconds is None
    assert length.timer_seconds is None
    assert length.swim_seconds is None
    assert length.rest_seconds is None
    assert interval.elapsed_seconds is None
    assert interval.timer_seconds is None


def test_uow_invalidates_known_parser_v1_moving_alias_on_read() -> None:
    normalization_id = EntityId.new()
    user_id = EntityId.new()
    activity_id = EntityId.new()
    artifact_id = EntityId.new()
    model = SimpleNamespace(
        id=normalization_id.value,
        user_id=user_id.value,
        activity_id=activity_id.value,
        artifact_id=artifact_id.value,
        parser_version="garmin-fit-sdk:test|swim-coach:1.0.0",
        profile_version="test",
        input_checksum="a" * 64,
        pool_length_m=20,
        distance_m=100,
        elapsed_seconds=Decimal("65"),
        timer_seconds=Decimal("60"),
        moving_seconds=Decimal("60"),
        active_length_count=5,
        completeness=Decimal("0.8"),
        quality="complete",
        warnings_json=[],
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        swim_seconds=None,
        rest_seconds=None,
        stationary_seconds=None,
        garmin_reported_speed_m_per_s=Decimal("0.591715976"),
        pace_from_garmin_reported_speed_seconds_per_100m=None,
        moving_pace_seconds_per_100m=None,
        swim_pace_seconds_per_100m=None,
        timer_pace_seconds_per_100m=None,
        session_pace_seconds_per_100m=None,
        perceived_effort_rpe=Decimal("3.0"),
        feeling_score=75,
        provenance_json={},
    )

    normalization = _normalization(model)

    assert normalization.moving_seconds is None
    assert normalization.garmin_reported_speed_m_per_s == Decimal("0.591715976")
    assert normalization.perceived_effort_rpe == Decimal("3.0")
    assert normalization.feeling_score == 75
    assert "LEGACY_V1_MOVING_DURATION_INVALIDATED" in normalization.warnings
    assert normalization.provenance["moving_seconds"]["interpretation"] == (
        "legacy_v1_timer_alias_invalidated"
    )

    with pytest.raises(DomainValidationError, match="RPE must be between 0 and 10"):
        replace(normalization, perceived_effort_rpe=Decimal("10.1"))
    with pytest.raises(DomainValidationError, match=r"0\.1 increments"):
        replace(normalization, perceived_effort_rpe=Decimal("3.05"))
    with pytest.raises(DomainValidationError, match="feeling score"):
        replace(normalization, feeling_score=101)


def test_legacy_child_provenance_marks_v2_fields_unavailable() -> None:
    provenance = _legacy_child_provenance({}, legacy_v1=True)

    assert provenance["canonical_v2"] == {
        "source": "inferred",
        "interpretation": "legacy_v1_fields_unavailable",
    }
