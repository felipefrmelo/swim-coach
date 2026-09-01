import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from swim_coach.application.ports.garmin import GarminErrorCategory, GarminProviderError
from swim_coach.infrastructure.garmin.provider import map_activity

FIXTURES = Path(__file__).parents[1] / "fixtures" / "garmin"


def test_provider_maps_allowlisted_pool_swim_fixture() -> None:
    item = map_activity(
        {
            "activityId": 123456,
            "activityName": "Piscina terça",
            "activityType": {"typeKey": "lap_swimming", "parentTypeId": 4},
            "startTimeGMT": "2026-08-10 21:00:00",
            "startTimeLocal": "2026-08-10 18:00:00",
            "distance": 2000.0,
            "duration": 2700.25,
            "elapsedDuration": 2800,
            "movingDuration": 2680,
            "poolLength": 2000,
            "poolLengthUnit": "meter",
            "unitOfPoolLength": "m",
            "numberOfActiveLengths": 100,
            "averageHR": 142,
            "avgSwolf": 37,
            "serialNumber": "must-not-leak",
            "ownerEmail": "must-not-leak@example.test",
        }
    )

    assert item.external_id == "123456"
    assert item.start_time_utc == datetime(2026, 8, 10, 21, tzinfo=UTC)
    assert item.start_time_local_wall == datetime(2026, 8, 10, 18)
    assert item.start_time_local_wall.tzinfo is None
    assert item.timezone is None
    assert item.elapsed_seconds == Decimal("2800")
    assert item.pool_length_m == 20
    assert item.length_count * item.pool_length_m == item.distance_m
    assert item.provenance["pool_length_m"] == {
        "source": "INFERRED",
        "raw_source": "GARMIN",
        "semantic_status": "INFERRED",
        "source_endpoint": "/activitylist-service/activities/search/activities",
        "raw_field": "poolLength",
        "raw_unit": "hundredth_of_metre",
        "normalized_unit": "metre",
        "transformation": "poolLength / 100",
        "raw_value": "2000",
        "normalized_value": 20,
        "value_status": "normalized",
        "distance_length_check": "matched",
        "expected_distance_m": 2000,
        "raw_unit_fields": {"poolLengthUnit": "meter", "unitOfPoolLength": "m"},
    }
    assert "GARMIN_SUMMARY_POOL_LENGTH_UNIT_INFERRED" in item.warnings
    assert item.raw_safe["poolLength"] == 2000
    assert item.raw_safe["startTimeLocal"] == "2026-08-10 18:00:00"
    assert item.raw_safe["activityType"] == {
        "typeKey": "lap_swimming",
        "parentTypeId": 4,
    }
    assert "serialNumber" not in item.raw_safe
    assert "ownerEmail" not in item.raw_safe


def test_provider_normalizes_real_20m_pool_summary_without_changing_durations() -> None:
    fixture = json.loads((FIXTURES / "pool_swim_860m_sanitized.json").read_text())
    # The versioned real-data projection intentionally contains no identifier,
    # name or timestamp. Add clearly synthetic required adapter fields here.
    item = map_activity(
        {
            **fixture["connect_summary_observation"],
            "activityId": "synthetic-provider-fixture",
            "activityName": "Synthetic pool summary",
            "startTimeGMT": "2000-01-01 12:00:00",
            "startTimeLocal": "2000-01-01 09:00:00",
        }
    )

    assert item.pool_length_m == 20
    assert item.length_count == 43
    assert item.distance_m == 860
    assert item.length_count * item.pool_length_m == item.distance_m
    assert item.moving_seconds == Decimal("1699.541")
    assert item.timer_seconds == Decimal("2075.559")
    assert item.elapsed_seconds == Decimal("2089.629")
    assert item.avg_pace_seconds_per_100m == Decimal("241.344")
    assert item.provenance["avg_pace_seconds_per_100m"] == {
        "source": "GARMIN",
        "semantic_status": "INFERRED",
        "source_endpoint": "/activitylist-service/activities/search/activities",
        "raw_field": "averagePace",
        "note": "unit and calculation basis are not documented by this endpoint",
    }
    assert item.start_time_utc == datetime(2000, 1, 1, 12, tzinfo=UTC)
    assert item.start_time_local_wall == datetime(2000, 1, 1, 9)
    assert item.timezone is None
    assert item.provenance["timezone"] == {
        "source": "INFERRED",
        "semantic_status": "INFERRED",
        "value_status": "unavailable_from_summary",
        "note": "application service must apply the athlete IANA timezone",
    }


def test_provider_does_not_invent_missing_moving_duration_or_timezone() -> None:
    item = map_activity(
        {
            "activityId": 987655,
            "activityName": "Pool swim",
            "activityType": {"typeKey": "lap_swimming"},
            "startTimeGMT": "2001-02-03 12:34:56+00:00",
            "startTimeLocal": "2001-02-03 09:34:56-03:00",
            "distance": 40,
            "duration": 100,
            "elapsedDuration": 110,
            "poolLength": 2000,
            "numberOfActiveLengths": 2,
        }
    )

    assert item.moving_seconds is None
    assert item.timezone is None
    assert item.start_time_local_wall == datetime(2001, 2, 3, 9, 34, 56)
    assert "GARMIN_SUMMARY_MOVING_DURATION_MISSING" in item.warnings
    assert "GARMIN_SUMMARY_LOCAL_WALL_TIME_CONTAINED_OFFSET" in item.warnings


def test_provider_reports_pool_distance_mismatch_without_forcing_the_invariant() -> None:
    item = map_activity(
        {
            "activityId": 987656,
            "activityName": "Incomplete pool swim",
            "activityType": {"typeKey": "lap_swimming"},
            "startTimeGMT": "2001-02-03 12:34:56",
            "distance": 60,
            "duration": 100,
            "elapsedDuration": 110,
            "movingDuration": 90,
            "poolLength": 2000,
            "numberOfActiveLengths": 2,
        }
    )

    assert item.pool_length_m == 20
    assert item.distance_m == 60
    assert item.length_count == 2
    assert "GARMIN_SUMMARY_POOL_LENGTH_DISTANCE_MISMATCH" in item.warnings
    pool_provenance = item.provenance["pool_length_m"]
    assert isinstance(pool_provenance, dict)
    assert pool_provenance["distance_length_check"] == "mismatched"
    assert pool_provenance["expected_distance_m"] == 40


def test_provider_classifies_missing_required_shape() -> None:
    with pytest.raises(GarminProviderError) as captured:
        map_activity({"activityId": 1})
    assert captured.value.category is GarminErrorCategory.SCHEMA_CHANGED
    assert captured.value.retryable is False


def test_provider_rejects_fractional_values_in_integer_summary_fields() -> None:
    with pytest.raises(GarminProviderError) as captured:
        map_activity(
            {
                "activityId": 987657,
                "activityName": "Fractional distance",
                "activityType": {"typeKey": "lap_swimming"},
                "startTimeGMT": "2001-02-03 12:34:56",
                "distance": 860.5,
                "duration": 100,
                "elapsedDuration": 110,
                "poolLength": 2000,
                "numberOfActiveLengths": 43,
            }
        )

    assert captured.value.category is GarminErrorCategory.SCHEMA_CHANGED
