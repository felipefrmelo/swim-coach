import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from garmin_fit_sdk import Encoder, Profile  # type: ignore[import-untyped]

from swim_coach.domain.shared.errors import DomainError
from swim_coach.domain.shared.value_objects import EntityId, UserId
from swim_coach.infrastructure.fit import GarminFitActivityParser

FIXTURES = Path(__file__).parents[1] / "fixtures" / "p03"
GARMIN_FIXTURES = Path(__file__).parents[1] / "fixtures" / "garmin"


def _messages() -> dict[str, Any]:
    result = json.loads((FIXTURES / "pool_swim_120m.json").read_text())
    result.pop("license")
    for key in ("session_mesgs", "lap_mesgs", "length_mesgs"):
        for item in result[key]:
            if "start_time" in item:
                item["start_time"] = datetime.fromisoformat(item["start_time"])
    return result


def _real_regression_messages() -> dict[str, Any]:
    fixture = json.loads((GARMIN_FIXTURES / "pool_swim_860m_sanitized.json").read_text())
    assert fixture["evidence_status"] == "MIXED_DOCUMENTED_AND_INFERRED"
    assert fixture["source_fit_available_during_fixture_creation"] is True
    assert fixture["raw_fit_versioned"] is False
    messages = fixture["fit_messages"]
    session = messages["session_mesgs"][0]
    assert "total_moving_time" not in session
    # Original timestamps and identifiers are intentionally absent. Indices,
    # rather than timestamps, own the decoded FIT length messages.
    started_at = datetime(2000, 1, 1, 12, tzinfo=UTC)
    return {
        **messages,
        "session_mesgs": [{**session, "start_time": started_at}],
    }


def test_synthetic_fixture_matches_golden_output() -> None:
    parser = GarminFitActivityParser()
    normalized = parser.normalize_messages(
        _messages(),
        user_id=UserId.new(),
        activity_id=EntityId.new(),
        artifact_id=EntityId.new(),
        input_checksum="a" * 64,
        fallback_pool_length_m=20,
    )
    item = normalized.normalization
    actual = {
        "active_length_count": item.active_length_count,
        "completeness": format(item.completeness, "f"),
        "distance_m": item.distance_m,
        "elapsed_seconds": format(item.elapsed_seconds, "f"),
        "interval_distances_m": [interval.distance_m for interval in normalized.intervals],
        "interval_paces_seconds_per_100m": [
            format(interval.pace_seconds_per_100m, "f")
            for interval in normalized.intervals
            if interval.pace_seconds_per_100m is not None
        ],
        "moving_seconds": format(item.moving_seconds, "f") if item.moving_seconds else None,
        "pool_length_m": item.pool_length_m,
        "quality": item.quality.value,
        "timer_seconds": format(item.timer_seconds, "f"),
        "warnings": list(item.warnings),
    }
    expected = json.loads((FIXTURES / "pool_swim_120m.golden.json").read_text())
    assert actual == expected
    assert sum(length.distance_m for length in normalized.lengths) == 120


def test_missing_lengths_yields_explicit_partial_quality() -> None:
    messages = _messages()
    messages["length_mesgs"] = []
    normalized = GarminFitActivityParser().normalize_messages(
        messages,
        user_id=UserId.new(),
        activity_id=EntityId.new(),
        artifact_id=EntityId.new(),
        input_checksum=hashlib.sha256(b"no-lengths").hexdigest(),
        fallback_pool_length_m=20,
    )
    assert normalized.normalization.distance_m == 120
    assert "LENGTH_MESSAGES_UNAVAILABLE" in normalized.normalization.warnings
    assert normalized.lengths == ()


def test_missing_laps_are_synthesized_but_reduce_completeness() -> None:
    messages = _messages()
    messages["lap_mesgs"] = []
    normalized = GarminFitActivityParser().normalize_messages(
        messages,
        user_id=UserId.new(),
        activity_id=EntityId.new(),
        artifact_id=EntityId.new(),
        input_checksum=hashlib.sha256(b"no-laps").hexdigest(),
        fallback_pool_length_m=20,
    )
    assert len(normalized.laps) == 1
    assert normalized.normalization.completeness == Decimal("0.900")
    assert normalized.normalization.quality.value == "partial"
    assert "LAP_MESSAGES_SYNTHESIZED" in normalized.normalization.warnings
    synthesized_lap = normalized.laps[0]
    synthesized_interval = normalized.intervals[0]
    assert synthesized_lap.garmin_reported_speed_m_per_s == Decimal("0.666666667")
    assert synthesized_lap.provenance["elapsed_seconds"]["raw_field"] == (
        "session.total_elapsed_time"
    )
    assert synthesized_lap.provenance["timer_seconds"]["raw_field"] == ("session.total_timer_time")
    assert synthesized_lap.provenance["moving_seconds"]["raw_field"] == (
        "session.total_moving_time"
    )
    assert synthesized_interval.source["synthesized_from_session"] is True
    for provenance in (synthesized_lap.provenance, synthesized_interval.provenance):
        assert all(
            not str(fact.get("raw_field", "")).startswith("lap.")
            for fact in provenance.values()
            if isinstance(fact, dict)
        )


def test_official_sdk_binary_round_trip_is_normalized() -> None:
    started_at = datetime(2026, 1, 1, tzinfo=UTC)
    encoder = Encoder()
    encoder.on_mesg(
        Profile["mesg_num"]["FILE_ID"],
        {
            "type": "activity",
            "manufacturer": "development",
            "product": 1,
            "time_created": started_at,
        },
    )
    encoder.on_mesg(
        Profile["mesg_num"]["SESSION"],
        {
            "sport": "swimming",
            "sub_sport": "lap_swimming",
            "start_time": started_at,
            "timestamp": started_at + timedelta(seconds=65),
            "total_elapsed_time": 65,
            "total_timer_time": 60,
            "total_distance": 40,
            "pool_length": 20,
            "pool_length_unit": "metric",
        },
    )
    encoder.on_mesg(
        Profile["mesg_num"]["LAP"],
        {
            "message_index": 0,
            "start_time": started_at,
            "timestamp": started_at + timedelta(seconds=65),
            "total_elapsed_time": 65,
            "total_timer_time": 60,
            "total_distance": 40,
            "sport": "swimming",
            "sub_sport": "lap_swimming",
        },
    )
    for index in range(2):
        encoder.on_mesg(
            Profile["mesg_num"]["LENGTH"],
            {
                "message_index": index,
                "start_time": started_at + timedelta(seconds=index * 30),
                "timestamp": started_at + timedelta(seconds=(index + 1) * 30),
                "total_elapsed_time": 30,
                "total_timer_time": 30,
                "length_type": "active",
                "swim_stroke": "freestyle",
                "total_strokes": 18,
                "avg_swimming_cadence": 36,
            },
        )
    data = bytes(encoder.close())

    normalized = GarminFitActivityParser().normalize(
        data,
        user_id=UserId.new(),
        activity_id=EntityId.new(),
        artifact_id=EntityId.new(),
        input_checksum=hashlib.sha256(data).hexdigest(),
        fallback_pool_length_m=25,
    )

    assert normalized.normalization.distance_m == 40
    assert normalized.normalization.pool_length_m == 20
    assert normalized.normalization.active_length_count == 2
    assert [item.stroke_count for item in normalized.lengths] == [18, 18]
    first_length = normalized.lengths[0]
    assert first_length.provenance["length_type"]["source"] == "garmin"
    assert first_length.provenance["distance_m"] == {
        "source": "derived",
        "interpretation": "inferred",
        "raw_field": "length.length_type",
        "transformation": "active FIT length_type * normalized pool_length_m",
    }
    assert first_length.provenance["detected_stroke"]["source"] == "garmin"
    assert first_length.provenance["stroke_count"]["interpretation"] == "documented"
    assert first_length.provenance["stroke_rate"] == {
        "source": "garmin",
        "interpretation": "documented",
        "raw_field": "length.avg_swimming_cadence",
        "transformation": "FIT SDK profile scaling to strokes per minute",
    }


def test_v2_preserves_idle_lengths_and_distinguishes_all_duration_and_pace_facts() -> None:
    started_at = datetime(2000, 1, 1, 12, 0, 0, tzinfo=UTC)
    messages = {
        "session_mesgs": [
            {
                "start_time": started_at,
                "pool_length": 20,
                "total_distance": 40,
                "total_elapsed_time": Decimal("75"),
                "total_timer_time": Decimal("70"),
                "total_moving_time": Decimal("35"),
                "avg_speed": Decimal("0.5"),
            }
        ],
        "lap_mesgs": [
            {
                "message_index": 0,
                "first_length_index": 0,
                "num_lengths": 2,
                "start_time": started_at,
                "total_distance": 40,
                "total_elapsed_time": 40,
                "total_timer_time": 40,
                "total_moving_time": 35,
                "avg_speed": Decimal("0.591715976"),
                "swim_stroke": "freestyle",
            },
            {
                "message_index": 1,
                "first_length_index": 2,
                "num_lengths": 1,
                "start_time": started_at + timedelta(seconds=40),
                "total_distance": 0,
                "total_elapsed_time": 25,
                "total_timer_time": 25,
                "total_moving_time": 0,
            },
        ],
        "length_mesgs": [
            {
                "start_time": started_at,
                "length_type": "active",
                "total_elapsed_time": 20,
                "total_timer_time": 20,
                "average_speed": Decimal("1"),
                "swim_stroke": "freestyle",
            },
            {
                "start_time": started_at + timedelta(seconds=20),
                "length_type": "active",
                "total_elapsed_time": 20,
                "total_timer_time": 20,
                "swim_stroke": "freestyle",
            },
            {
                "start_time": started_at + timedelta(seconds=40),
                "length_type": "idle",
                "total_elapsed_time": 25,
                "total_timer_time": 25,
            },
        ],
    }
    normalized = GarminFitActivityParser().normalize_messages(
        messages,
        user_id=UserId.new(),
        activity_id=EntityId.new(),
        artifact_id=EntityId.new(),
        input_checksum=hashlib.sha256(b"v2-duration-semantics").hexdigest(),
        fallback_pool_length_m=25,
    )

    item = normalized.normalization
    assert item.pool_length_m == 20
    assert item.distance_m == 40
    assert item.elapsed_seconds == Decimal("75")
    assert item.timer_seconds == Decimal("70")
    assert item.moving_seconds == Decimal("35")
    assert item.swim_seconds == Decimal("40")
    assert item.rest_seconds == Decimal("25")
    assert item.stationary_seconds == Decimal("10")
    assert item.garmin_reported_speed_m_per_s == Decimal("0.5")
    assert item.moving_pace_seconds_per_100m == Decimal("87.5")
    assert item.timer_pace_seconds_per_100m == Decimal("175")
    assert item.pace_from_garmin_reported_speed_seconds_per_100m == Decimal("2E+2")
    assert normalized.laps[0].garmin_reported_speed_m_per_s == Decimal("0.591715976")
    assert normalized.intervals[0].garmin_reported_speed_m_per_s == Decimal("0.591715976")
    assert item.provenance["garmin_reported_speed_m_per_s"]["source"] == "garmin"
    assert item.provenance["garmin_reported_speed_m_per_s"]["field_unit_semantics"] == (
        "documented"
    )
    assert item.provenance["garmin_reported_speed_m_per_s"]["calculation_basis"] == "inferred"
    assert item.provenance["garmin_reported_speed_m_per_s"]["interpretation"] == "inferred"
    assert item.provenance["pace_from_garmin_reported_speed_seconds_per_100m"]["source"] == (
        "derived"
    )
    assert (
        item.provenance["pace_from_garmin_reported_speed_seconds_per_100m"][
            "input_calculation_basis"
        ]
        == "inferred"
    )
    assert normalized.laps[0].provenance["garmin_reported_speed_m_per_s"]["source"] == ("garmin")
    assert (
        normalized.laps[0].provenance["pace_from_garmin_reported_speed_seconds_per_100m"]["source"]
        == "derived"
    )
    assert [interval.interval_type for interval in normalized.intervals] == ["swim", "rest"]
    first_lap = normalized.laps[0]
    first_interval = normalized.intervals[0]
    for parsed in (first_lap, first_interval):
        assert parsed.provenance["distance_m"] == {
            "source": "garmin",
            "interpretation": "documented",
            "raw_field": "lap.total_distance",
            "transformation": "FIT SDK profile scaling to metres",
        }
        assert parsed.provenance["detected_stroke"]["source"] == "garmin"
        assert parsed.provenance["detected_stroke"]["raw_field"] == "lap.swim_stroke"
        assert parsed.provenance["stroke_count"]["source"] == "inferred"
        assert parsed.provenance["stroke_rate"]["source"] == "inferred"
        assert parsed.provenance["swolf"]["source"] == "inferred"
    assert first_interval.provenance["interval_type"] == {
        "source": "derived",
        "interpretation": "inferred",
        "raw_field": "lap.total_distance",
        "transformation": "positive-distance lap canonical classification",
    }
    assert normalized.intervals[0].pace_from_garmin_reported_speed_seconds_per_100m != (
        normalized.intervals[0].timer_pace_seconds_per_100m
    )
    assert [length.length_type for length in normalized.lengths] == [
        "active",
        "active",
        "idle",
    ]
    assert [length.distance_m for length in normalized.lengths] == [20, 20, 0]
    assert normalized.lengths[0].garmin_reported_speed_m_per_s == Decimal("1")
    assert normalized.lengths[0].pace_from_garmin_reported_speed_seconds_per_100m == Decimal(
        "100.000"
    )
    assert normalized.lengths[0].provenance["garmin_reported_speed_m_per_s"]["raw_field"] == (
        "length.average_speed"
    )
    assert (
        normalized.lengths[0].provenance["garmin_reported_speed_m_per_s"]["interpretation"]
        == "inferred"
    )
    assert (
        normalized.lengths[0].provenance["pace_from_garmin_reported_speed_seconds_per_100m"][
            "source"
        ]
        == "derived"
    )
    assert "LAP_PACE_FROM_GARMIN_REPORTED_SPEED_DIFFERS_FROM_TIMER_PACE" in item.warnings
    assert item.provenance["pool_length_m"]["source"] == "garmin"


def test_zero_count_rest_lap_owns_idle_length_until_next_fit_boundary() -> None:
    """Garmin may exclude an idle length from a rest lap's num_lengths count."""

    started_at = datetime(2000, 1, 1, 12, 0, 0, tzinfo=UTC)
    messages = {
        "session_mesgs": [
            {
                "start_time": started_at,
                "pool_length": 20,
                "total_distance": 60,
                "total_elapsed_time": 85,
                "total_timer_time": 85,
                "total_moving_time": 60,
                "num_active_lengths": 3,
            }
        ],
        "lap_mesgs": [
            {
                "message_index": 0,
                "first_length_index": 0,
                "num_lengths": 2,
                "start_time": started_at,
                "total_distance": 40,
                "total_elapsed_time": 40,
                "total_timer_time": 40,
                "total_moving_time": 40,
            },
            {
                "message_index": 1,
                "first_length_index": 2,
                "num_lengths": 0,
                "start_time": started_at + timedelta(seconds=40),
                "total_distance": 0,
                "total_elapsed_time": 25,
                "total_timer_time": 25,
                "total_moving_time": 0,
            },
            {
                "message_index": 2,
                "first_length_index": 3,
                "num_lengths": 1,
                "start_time": started_at + timedelta(seconds=65),
                "total_distance": 20,
                "total_elapsed_time": 20,
                "total_timer_time": 20,
                "total_moving_time": 20,
            },
        ],
        "length_mesgs": [
            {
                "message_index": 0,
                "start_time": started_at,
                "length_type": "active",
                "total_elapsed_time": 20,
                "total_timer_time": 20,
                "swim_stroke": "freestyle",
            },
            {
                "message_index": 1,
                "start_time": started_at + timedelta(seconds=20),
                "length_type": "active",
                "total_elapsed_time": 20,
                "total_timer_time": 20,
                "swim_stroke": "freestyle",
            },
            {
                "message_index": 2,
                "start_time": started_at + timedelta(seconds=40),
                "length_type": "idle",
                "total_elapsed_time": 25,
                "total_timer_time": 25,
            },
            {
                "message_index": 3,
                "start_time": started_at + timedelta(seconds=65),
                "length_type": "active",
                "total_elapsed_time": 20,
                "total_timer_time": 20,
                "swim_stroke": "freestyle",
            },
        ],
    }

    normalized = GarminFitActivityParser().normalize_messages(
        messages,
        user_id=UserId.new(),
        activity_id=EntityId.new(),
        artifact_id=EntityId.new(),
        input_checksum=hashlib.sha256(b"zero-count-rest-lap-boundary").hexdigest(),
        fallback_pool_length_m=25,
    )

    assert len(normalized.lengths) == 4
    assert [length.length_type for length in normalized.lengths] == [
        "active",
        "active",
        "idle",
        "active",
    ]
    assert normalized.intervals[1].interval_type == "rest"
    assert normalized.intervals[1].rest_seconds == Decimal("25.000")
    assert normalized.normalization.rest_seconds == Decimal("25.000")
    assert normalized.lengths[2].interval_id == normalized.intervals[1].id
    assert normalized.lengths[3].interval_id == normalized.intervals[2].id
    assert normalized.normalization.parser_version.endswith("|swim-coach:2.0.4")
    assert "UNASSIGNED_LENGTH_MESSAGES" not in normalized.normalization.warnings
    assert "LAP_IDLE_LENGTH_OWNERSHIP_INFERRED" in normalized.normalization.warnings
    assert "ZERO_DISTANCE_INTERVAL_WITHOUT_REST_EVIDENCE" not in (normalized.normalization.warnings)


def test_positive_count_lap_does_not_absorb_gap_before_next_boundary() -> None:
    started_at = datetime(2000, 1, 1, 12, 0, 0, tzinfo=UTC)
    messages = {
        "session_mesgs": [
            {
                "start_time": started_at,
                "pool_length": 20,
                "total_distance": 40,
                "total_elapsed_time": 40,
                "total_timer_time": 40,
                "total_moving_time": 40,
                "num_active_lengths": 4,
            }
        ],
        "lap_mesgs": [
            {
                "message_index": 0,
                "first_length_index": 0,
                "num_lengths": 1,
                "total_distance": 20,
                "total_elapsed_time": 20,
                "total_timer_time": 20,
                "total_moving_time": 20,
            },
            {
                "message_index": 1,
                "first_length_index": 3,
                "num_lengths": 1,
                "total_distance": 20,
                "total_elapsed_time": 20,
                "total_timer_time": 20,
                "total_moving_time": 20,
            },
        ],
        "length_mesgs": [
            {
                "message_index": index,
                "length_type": "active",
                "total_elapsed_time": 20,
                "total_timer_time": 20,
            }
            for index in range(4)
        ],
    }

    normalized = GarminFitActivityParser().normalize_messages(
        messages,
        user_id=UserId.new(),
        activity_id=EntityId.new(),
        artifact_id=EntityId.new(),
        input_checksum=hashlib.sha256(b"positive-count-gap").hexdigest(),
        fallback_pool_length_m=20,
    )

    assert len(normalized.lengths) == 2
    assert normalized.laps[0].swim_seconds == Decimal("20.000")
    assert normalized.laps[1].swim_seconds == Decimal("20.000")
    assert "LAP_LENGTH_INDEX_COUNT_MISMATCH" in normalized.normalization.warnings
    assert "UNASSIGNED_LENGTH_MESSAGES" in normalized.normalization.warnings


def test_next_lap_boundary_prevents_overlapping_length_ownership() -> None:
    started_at = datetime(2000, 1, 1, 12, 0, 0, tzinfo=UTC)
    messages = {
        "session_mesgs": [
            {
                "start_time": started_at,
                "pool_length": 20,
                "total_distance": 40,
                "total_elapsed_time": 40,
                "total_timer_time": 40,
                "total_moving_time": 40,
                "num_active_lengths": 2,
            }
        ],
        "lap_mesgs": [
            {
                "message_index": 0,
                "first_length_index": 0,
                # Corrupt/inconsistent count crosses the next lap boundary.
                "num_lengths": 2,
                "start_time": started_at,
                "total_distance": 20,
                "total_elapsed_time": 20,
                "total_timer_time": 20,
                "total_moving_time": 20,
            },
            {
                "message_index": 1,
                "first_length_index": 1,
                "num_lengths": 1,
                "start_time": started_at + timedelta(seconds=20),
                "total_distance": 20,
                "total_elapsed_time": 20,
                "total_timer_time": 20,
                "total_moving_time": 20,
            },
        ],
        "length_mesgs": [
            {
                "message_index": index,
                "start_time": started_at + timedelta(seconds=20 * index),
                "length_type": "active",
                "total_elapsed_time": 20,
                "total_timer_time": 20,
                "swim_stroke": "freestyle",
            }
            for index in range(2)
        ],
    }

    normalized = GarminFitActivityParser().normalize_messages(
        messages,
        user_id=UserId.new(),
        activity_id=EntityId.new(),
        artifact_id=EntityId.new(),
        input_checksum=hashlib.sha256(b"overlapping-length-boundary").hexdigest(),
        fallback_pool_length_m=25,
    )

    assert len(normalized.lengths) == 2
    assert normalized.lengths[0].interval_id == normalized.intervals[0].id
    assert normalized.lengths[1].interval_id == normalized.intervals[1].id
    assert "LAP_LENGTH_INDEX_RANGE_OVERLAP" in normalized.normalization.warnings
    assert normalized.normalization.quality.value == "partial"


def test_missing_moving_time_is_not_silently_replaced_by_timer_time() -> None:
    messages = _messages()
    messages["session_mesgs"][0].pop("total_moving_time")
    normalized = GarminFitActivityParser().normalize_messages(
        messages,
        user_id=UserId.new(),
        activity_id=EntityId.new(),
        artifact_id=EntityId.new(),
        input_checksum=hashlib.sha256(b"missing-moving").hexdigest(),
        fallback_pool_length_m=20,
    )
    assert normalized.normalization.moving_seconds is None
    assert normalized.normalization.moving_pace_seconds_per_100m is None
    assert normalized.normalization.quality.value == "partial"
    assert "MOVING_DURATION_UNAVAILABLE" in normalized.normalization.warnings
    assert normalized.normalization.provenance["moving_seconds"]["source"] == "inferred"


def test_fit_profile_facts_and_non_standard_swolf_have_explicit_provenance() -> None:
    messages = _messages()
    messages["session_mesgs"][0]["pool_length_unit"] = "metric"
    messages["session_mesgs"][0]["num_active_lengths"] = 6
    messages["lap_mesgs"][0]["avg_cadence"] = 36

    normalized = GarminFitActivityParser().normalize_messages(
        messages,
        user_id=UserId.new(),
        activity_id=EntityId.new(),
        artifact_id=EntityId.new(),
        input_checksum=hashlib.sha256(b"field-provenance").hexdigest(),
        fallback_pool_length_m=20,
    )

    item = normalized.normalization
    assert item.quality.value == "partial"
    assert item.provenance["pool_length_unit"] == {
        "source": "garmin",
        "interpretation": "documented",
        "raw_field": "session.pool_length_unit",
        "garmin_value": "metric",
    }
    assert item.provenance["active_length_count"] == {
        "source": "derived",
        "interpretation": "documented",
        "raw_field": "length.length_type",
        "transformation": "count persisted decoded active length messages",
        "garmin_reported_value": 6,
        "garmin_raw_field": "session.num_active_lengths",
        "decoded_message_value": 6,
        "persisted_value": 6,
    }
    lap = normalized.laps[0]
    interval = normalized.intervals[0]
    for parsed in (lap, interval):
        assert parsed.provenance["stroke_count"] == {
            "source": "garmin",
            "interpretation": "documented",
            "raw_field": "lap.total_strokes",
            "transformation": "FIT swimming total_strokes field",
        }
        assert parsed.provenance["stroke_rate"] == {
            "source": "garmin",
            "interpretation": "inferred",
            "raw_field": "lap.avg_cadence",
            "transformation": "map generic FIT avg_cadence rpm to canonical stroke rate",
        }
        assert parsed.provenance["swolf"] == {
            "source": "garmin",
            "interpretation": "inferred",
            "raw_field": "lap.avg_swolf",
            "transformation": "non-standard decoded lap/session field preserved",
        }
    length = normalized.lengths[0]
    assert length.provenance["stroke_count"]["source"] == "garmin"
    assert length.provenance["stroke_rate"]["source"] == "inferred"
    assert length.provenance["swolf"] == {
        "source": "derived",
        "interpretation": "inferred",
        "transformation": "timer_seconds + stroke_count",
    }


def test_session_active_length_count_mismatch_is_preserved_as_quality_warning() -> None:
    messages = _messages()
    messages["session_mesgs"][0]["num_active_lengths"] = 43

    normalized = GarminFitActivityParser().normalize_messages(
        messages,
        user_id=UserId.new(),
        activity_id=EntityId.new(),
        artifact_id=EntityId.new(),
        input_checksum=hashlib.sha256(b"active-length-count-mismatch").hexdigest(),
        fallback_pool_length_m=20,
    )

    item = normalized.normalization
    assert item.active_length_count == 6
    assert item.provenance["active_length_count"]["garmin_reported_value"] == 43
    assert item.provenance["active_length_count"]["decoded_message_value"] == 6
    assert "SESSION_ACTIVE_LENGTH_COUNT_MISMATCH" in item.warnings
    assert item.quality.value == "poor"


def test_missing_length_fields_are_explicitly_inferred_not_attributed_to_garmin() -> None:
    messages = _messages()
    messages["length_mesgs"][0].pop("swim_stroke")
    messages["length_mesgs"][1].pop("length_type")

    normalized = GarminFitActivityParser().normalize_messages(
        messages,
        user_id=UserId.new(),
        activity_id=EntityId.new(),
        artifact_id=EntityId.new(),
        input_checksum=hashlib.sha256(b"missing-length-fields").hexdigest(),
        fallback_pool_length_m=20,
    )

    stroke_fallback = normalized.lengths[0]
    assert stroke_fallback.detected_stroke == "freestyle"
    assert stroke_fallback.provenance["detected_stroke"] == {
        "source": "derived",
        "interpretation": "inferred",
        "raw_field": "lap.swim_stroke",
        "transformation": "canonical lap detected_stroke fallback",
    }
    unknown = normalized.lengths[1]
    assert unknown.length_type == "unknown"
    assert unknown.distance_m == 0
    assert unknown.provenance["length_type"] == {
        "source": "inferred",
        "interpretation": "inferred",
        "transformation": "missing field maps to unknown",
    }
    assert unknown.provenance["distance_m"]["source"] == "inferred"
    assert "UNKNOWN_LENGTH_TYPE" in normalized.normalization.warnings


def test_fractional_fit_metres_are_rejected_instead_of_truncated() -> None:
    messages = _messages()
    messages["session_mesgs"][0]["pool_length"] = Decimal("22.86")
    messages["session_mesgs"][0]["total_distance"] = Decimal("137.16")

    with pytest.raises(DomainError) as error:
        GarminFitActivityParser().normalize_messages(
            messages,
            user_id=UserId.new(),
            activity_id=EntityId.new(),
            artifact_id=EntityId.new(),
            input_checksum=hashlib.sha256(b"fractional-metres").hexdigest(),
            fallback_pool_length_m=25,
        )

    assert error.value.code == "FIT_DISTANCE_PRECISION_UNSUPPORTED"


def test_missing_timer_duration_is_explicitly_inferred_at_every_level() -> None:
    messages = _messages()
    messages["session_mesgs"][0].pop("total_timer_time")
    for item in (*messages["lap_mesgs"], *messages["length_mesgs"]):
        item.pop("total_timer_time", None)

    normalized = GarminFitActivityParser().normalize_messages(
        messages,
        user_id=UserId.new(),
        activity_id=EntityId.new(),
        artifact_id=EntityId.new(),
        input_checksum=hashlib.sha256(b"missing-timer").hexdigest(),
        fallback_pool_length_m=20,
    )

    item = normalized.normalization
    assert item.timer_seconds == item.elapsed_seconds
    assert "TIMER_DURATION_FALLBACK_INFERRED" in item.warnings
    assert item.provenance["timer_seconds"]["source"] == "inferred"
    assert all(lap.provenance["timer_seconds"]["source"] == "inferred" for lap in normalized.laps)
    assert all(
        length.provenance["timer_seconds"]["source"] == "inferred" for length in normalized.lengths
    )
    assert "LAP_TIMER_DURATION_FALLBACK_INFERRED" in item.warnings
    assert "LENGTH_TIMER_DURATION_FALLBACK_INFERRED" in item.warnings


def test_garmin_session_distance_remains_canonical_when_active_lengths_disagree() -> None:
    messages = _messages()
    messages["session_mesgs"][0]["total_distance"] = 1_000

    normalized = GarminFitActivityParser().normalize_messages(
        messages,
        user_id=UserId.new(),
        activity_id=EntityId.new(),
        artifact_id=EntityId.new(),
        input_checksum=hashlib.sha256(b"derived-distance").hexdigest(),
        fallback_pool_length_m=20,
    )

    item = normalized.normalization
    assert item.distance_m == 1_000
    assert "SESSION_LENGTH_DISTANCE_MISMATCH" in item.warnings
    assert "ACTIVE_LENGTH_DISTANCE_INVARIANT_FAILED" in item.warnings
    assert item.provenance["distance_m"] == {
        "source": "garmin",
        "interpretation": "documented",
        "raw_field": "session.total_distance",
        "transformation": "FIT SDK profile scaling to metres",
        "garmin_value_m": 1_000,
        "active_length_value_m": 120,
    }


def test_active_length_distance_is_used_only_when_session_distance_is_absent() -> None:
    messages = _messages()
    messages["session_mesgs"][0].pop("total_distance")

    normalized = GarminFitActivityParser().normalize_messages(
        messages,
        user_id=UserId.new(),
        activity_id=EntityId.new(),
        artifact_id=EntityId.new(),
        input_checksum=hashlib.sha256(b"missing-session-distance").hexdigest(),
        fallback_pool_length_m=20,
    )

    item = normalized.normalization
    assert item.distance_m == 120
    assert item.provenance["distance_m"] == {
        "source": "derived",
        "interpretation": "inferred",
        "transformation": "active length count * pool length metres",
        "active_length_value_m": 120,
    }


def test_explicit_zero_session_distance_is_not_treated_as_missing() -> None:
    messages = _messages()
    messages["session_mesgs"][0]["total_distance"] = 0

    normalized = GarminFitActivityParser().normalize_messages(
        messages,
        user_id=UserId.new(),
        activity_id=EntityId.new(),
        artifact_id=EntityId.new(),
        input_checksum=hashlib.sha256(b"zero-session-distance").hexdigest(),
        fallback_pool_length_m=20,
    )

    item = normalized.normalization
    assert item.distance_m == 0
    assert item.provenance["distance_m"]["source"] == "garmin"
    assert item.provenance["distance_m"]["garmin_value_m"] == 0
    assert item.provenance["distance_m"]["active_length_value_m"] == 120
    assert "SESSION_LENGTH_DISTANCE_MISMATCH" in item.warnings


def test_unassigned_length_messages_fail_the_persisted_length_invariant() -> None:
    started_at = datetime(2026, 1, 1, tzinfo=UTC)
    messages = {
        "session_mesgs": [
            {
                "start_time": started_at,
                "pool_length": 20,
                "total_distance": 100,
                "total_elapsed_time": 100,
                "total_timer_time": 100,
                "total_moving_time": 100,
            }
        ],
        "lap_mesgs": [
            {
                "message_index": 0,
                "first_length_index": 0,
                "num_lengths": 2,
                "start_time": started_at,
                "total_distance": 100,
                "total_elapsed_time": 100,
                "total_timer_time": 100,
                "total_moving_time": 100,
            }
        ],
        "length_mesgs": [
            {
                "message_index": index,
                "start_time": started_at + timedelta(seconds=index * 20),
                "length_type": "active",
                "total_elapsed_time": 20,
                "total_timer_time": 20,
            }
            for index in range(5)
        ],
    }

    normalized = GarminFitActivityParser().normalize_messages(
        messages,
        user_id=UserId.new(),
        activity_id=EntityId.new(),
        artifact_id=EntityId.new(),
        input_checksum=hashlib.sha256(b"unassigned-lengths").hexdigest(),
        fallback_pool_length_m=20,
    )

    item = normalized.normalization
    assert item.distance_m == 100
    assert item.active_length_count == 2
    assert len(normalized.lengths) == 2
    assert "UNASSIGNED_LENGTH_MESSAGES" in item.warnings
    assert "ACTIVE_LENGTH_DISTANCE_INVARIANT_FAILED" in item.warnings
    assert "LAP_ACTIVE_LENGTH_DISTANCE_MISMATCH" in item.warnings


def test_unknown_length_type_keeps_raw_source_but_marks_interpretation_inferred() -> None:
    messages = _messages()
    messages["length_mesgs"][0]["length_type"] = "transition"

    normalized = GarminFitActivityParser().normalize_messages(
        messages,
        user_id=UserId.new(),
        activity_id=EntityId.new(),
        artifact_id=EntityId.new(),
        input_checksum=hashlib.sha256(b"future-length-enum").hexdigest(),
        fallback_pool_length_m=20,
    )

    first = normalized.lengths[0]
    assert first.length_type == "unknown"
    assert first.provenance["length_type"] == {
        "source": "garmin",
        "interpretation": "inferred",
        "raw_field": "length.length_type",
        "transformation": "unrecognized FIT length_type value mapped to unknown",
    }
    assert normalized.normalization.quality.value != "complete"
    assert "UNKNOWN_LENGTH_TYPE" in normalized.normalization.warnings


def test_zero_fit_pool_length_uses_inferred_fallback_provenance() -> None:
    messages = _messages()
    messages["session_mesgs"][0]["pool_length"] = 0

    normalized = GarminFitActivityParser().normalize_messages(
        messages,
        user_id=UserId.new(),
        activity_id=EntityId.new(),
        artifact_id=EntityId.new(),
        input_checksum=hashlib.sha256(b"zero-pool").hexdigest(),
        fallback_pool_length_m=20,
    )

    item = normalized.normalization
    assert item.pool_length_m == 20
    assert item.quality.value == "partial"
    assert "POOL_LENGTH_FALLBACK_INFERRED" in item.warnings
    assert item.provenance["pool_length_m"] == {
        "source": "inferred",
        "interpretation": "inferred",
        "transformation": (
            "corroborated ingestion fallback from activity summary and/or "
            "distance per active length"
        ),
        "garmin_value_m": 0,
        "fallback_value_m": 20,
    }


def test_broken_duration_invariant_is_preserved_with_poor_quality() -> None:
    messages = _messages()
    messages["session_mesgs"][0]["total_moving_time"] = Decimal("181")

    normalized = GarminFitActivityParser().normalize_messages(
        messages,
        user_id=UserId.new(),
        activity_id=EntityId.new(),
        artifact_id=EntityId.new(),
        input_checksum=hashlib.sha256(b"moving-exceeds-timer").hexdigest(),
        fallback_pool_length_m=20,
    )

    assert normalized.normalization.moving_seconds == Decimal("181")
    assert "SESSION_MOVING_EXCEEDS_TIMER" in normalized.normalization.warnings
    assert normalized.normalization.quality.value == "poor"


def test_fit_pool_fact_is_used_when_summary_fallback_is_unavailable() -> None:
    normalized = GarminFitActivityParser().normalize_messages(
        _messages(),
        user_id=UserId.new(),
        activity_id=EntityId.new(),
        artifact_id=EntityId.new(),
        input_checksum=hashlib.sha256(b"fit-pool-without-summary").hexdigest(),
        fallback_pool_length_m=None,
    )

    assert normalized.normalization.pool_length_m == 20
    assert "POOL_LENGTH_FALLBACK_INFERRED" not in normalized.normalization.warnings


def test_zero_distance_without_idle_evidence_remains_unknown_not_rest() -> None:
    started_at = datetime(2026, 1, 1, tzinfo=UTC)
    messages = {
        "session_mesgs": [
            {
                "start_time": started_at,
                "pool_length": 20,
                "total_distance": 0,
                "total_elapsed_time": 25,
                "total_timer_time": 25,
                "total_moving_time": 0,
            }
        ],
        "lap_mesgs": [
            {
                "message_index": 0,
                "start_time": started_at,
                "total_distance": 0,
                "total_elapsed_time": 25,
                "total_timer_time": 25,
                "total_moving_time": 0,
            }
        ],
        "length_mesgs": [],
    }

    normalized = GarminFitActivityParser().normalize_messages(
        messages,
        user_id=UserId.new(),
        activity_id=EntityId.new(),
        artifact_id=EntityId.new(),
        input_checksum=hashlib.sha256(b"zero-distance-unknown").hexdigest(),
        fallback_pool_length_m=20,
    )

    interval = normalized.intervals[0]
    assert interval.interval_type == "unknown"
    assert interval.rest_seconds == Decimal(0)
    assert interval.stationary_seconds == Decimal("25.000")
    assert "ZERO_DISTANCE_INTERVAL_WITHOUT_REST_EVIDENCE" in interval.quality_warnings
    assert normalized.normalization.rest_seconds == Decimal("0.000")


def test_sanitized_real_860m_fit_preserves_distinct_clocks_paces_and_idle_rest() -> None:
    normalized = GarminFitActivityParser().normalize_messages(
        _real_regression_messages(),
        user_id=UserId.new(),
        activity_id=EntityId.new(),
        artifact_id=EntityId.new(),
        input_checksum=hashlib.sha256(b"sanitized-860m-regression").hexdigest(),
        fallback_pool_length_m=25,
    )
    item = normalized.normalization

    assert item.pool_length_m == 20
    assert item.active_length_count == 43
    assert item.distance_m == 860
    assert item.active_length_count * item.pool_length_m == item.distance_m
    assert item.moving_seconds is None
    assert item.timer_seconds == Decimal("2075.559")
    assert item.elapsed_seconds == Decimal("2089.629")
    assert item.swim_seconds == Decimal("1699.541")
    assert item.rest_seconds == Decimal("376.018")
    assert item.stationary_seconds is None
    assert item.moving_pace_seconds_per_100m is None
    assert item.swim_pace_seconds_per_100m == Decimal("197.621")
    assert item.timer_pace_seconds_per_100m == Decimal("241.344")
    assert item.session_pace_seconds_per_100m == Decimal("242.980")
    assert item.garmin_reported_speed_m_per_s == Decimal("0.506")
    assert item.pace_from_garmin_reported_speed_seconds_per_100m == Decimal("197.628")
    assert item.provenance["moving_seconds"]["transformation"] == "value unavailable"
    assert item.provenance["swim_seconds"]["source"] == "derived"
    assert item.provenance["rest_seconds"]["source"] == "derived"
    assert item.provenance["garmin_reported_speed_m_per_s"] == {
        "source": "garmin",
        "interpretation": "inferred",
        "raw_field": "session.enhanced_avg_speed",
        "transformation": "FIT SDK profile scaling to metres per second",
        "field_unit_semantics": "documented",
        "calculation_basis": "inferred",
    }
    assert (
        item.provenance["pace_from_garmin_reported_speed_seconds_per_100m"][
            "input_calculation_basis"
        ]
        == "inferred"
    )
    assert all(lap.moving_seconds is None for lap in normalized.laps)
    assert len(normalized.lengths) == 61
    assert sum(length.length_type == "active" for length in normalized.lengths) == 43
    assert sum(length.length_type == "idle" for length in normalized.lengths) == 18
    zero_distance = tuple(interval for interval in normalized.intervals if interval.distance_m == 0)
    assert len(zero_distance) == 14
    assert all(interval.interval_type == "rest" for interval in zero_distance)
    assert all(interval.rest_seconds > 0 for interval in zero_distance)
    assert "LAP_IDLE_LENGTH_OWNERSHIP_INFERRED" in item.warnings
    assert "UNASSIGNED_LENGTH_MESSAGES" not in item.warnings
    assert "ZERO_DISTANCE_INTERVAL_WITHOUT_REST_EVIDENCE" not in item.warnings
    first_80m = next(interval for interval in normalized.intervals if interval.distance_m == 80)
    assert first_80m.timer_seconds == Decimal("158.171")
    assert first_80m.swim_seconds == Decimal("135.171")
    assert first_80m.rest_seconds == Decimal("23.000")
    assert first_80m.garmin_reported_speed_m_per_s == Decimal("0.592")
    assert first_80m.pace_from_garmin_reported_speed_seconds_per_100m == Decimal("168.919")
    assert first_80m.swim_pace_seconds_per_100m == Decimal("168.964")
    assert first_80m.timer_pace_seconds_per_100m == Decimal("197.714")
    assert (
        "LAP_PACE_FROM_GARMIN_REPORTED_SPEED_DIFFERS_FROM_TIMER_PACE" in first_80m.quality_warnings
    )
    suspicious = next(
        length for length in normalized.lengths if length.timer_seconds == Decimal("72.770")
    )
    assert suspicious.detected_stroke == "breaststroke"


def test_corrupt_fit_is_rejected_without_partial_output() -> None:
    with pytest.raises(DomainError) as error:
        GarminFitActivityParser().normalize(
            b"not-a-fit",
            user_id=UserId.new(),
            activity_id=EntityId.new(),
            artifact_id=EntityId.new(),
            input_checksum=hashlib.sha256(b"not-a-fit").hexdigest(),
            fallback_pool_length_m=20,
        )
    assert error.value.code == "FIT_PARSE_FAILED"
