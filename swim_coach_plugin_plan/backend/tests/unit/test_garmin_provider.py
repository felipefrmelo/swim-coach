from datetime import UTC, datetime
from decimal import Decimal

import pytest

from swim_coach.application.ports.garmin import GarminErrorCategory, GarminProviderError
from swim_coach.infrastructure.garmin.provider import map_activity


def test_provider_maps_allowlisted_pool_swim_fixture() -> None:
    item = map_activity(
        {
            "activityId": 123456,
            "activityName": "Piscina terça",
            "activityType": {"typeKey": "lap_swimming", "parentTypeId": 4},
            "startTimeGMT": "2026-08-10 21:00:00",
            "distance": 2000.0,
            "duration": 2700.25,
            "elapsedDuration": 2800,
            "movingDuration": 2680,
            "poolLength": 20,
            "numberOfActiveLengths": 100,
            "averageHR": 142,
            "avgSwolf": 37,
            "serialNumber": "must-not-leak",
            "ownerEmail": "must-not-leak@example.test",
        }
    )

    assert item.external_id == "123456"
    assert item.start_time_utc == datetime(2026, 8, 10, 21, tzinfo=UTC)
    assert item.elapsed_seconds == Decimal("2800")
    assert item.pool_length_m == 20
    assert item.raw_safe["activityType"] == {
        "typeKey": "lap_swimming",
        "parentTypeId": 4,
    }
    assert "serialNumber" not in item.raw_safe
    assert "ownerEmail" not in item.raw_safe


def test_provider_classifies_missing_required_shape() -> None:
    with pytest.raises(GarminProviderError) as captured:
        map_activity({"activityId": 1})
    assert captured.value.category is GarminErrorCategory.SCHEMA_CHANGED
    assert captured.value.retryable is False
