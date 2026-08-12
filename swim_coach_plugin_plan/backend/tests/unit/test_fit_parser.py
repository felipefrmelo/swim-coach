import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from garmin_fit_sdk import Encoder, Profile  # type: ignore[import-untyped]

from swim_coach.domain.shared.errors import DomainError
from swim_coach.domain.shared.value_objects import EntityId, UserId
from swim_coach.infrastructure.fit import GarminFitActivityParser

FIXTURES = Path(__file__).parents[1] / "fixtures" / "p03"


def _messages() -> dict[str, Any]:
    result = json.loads((FIXTURES / "pool_swim_120m.json").read_text())
    result.pop("license")
    for key in ("session_mesgs", "lap_mesgs", "length_mesgs"):
        for item in result[key]:
            if "start_time" in item:
                item["start_time"] = datetime.fromisoformat(item["start_time"])
    return result


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
        "moving_seconds": format(item.moving_seconds, "f"),
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
    assert normalized.normalization.completeness == pytest.approx(0.875)
    assert "LAP_MESSAGES_SYNTHESIZED" in normalized.normalization.warnings


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
