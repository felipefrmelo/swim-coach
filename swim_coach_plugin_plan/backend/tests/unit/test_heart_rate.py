from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from test_activity_views_v2 import _synthetic_activity_fixture
from test_fit_parser import _messages

from swim_coach.application.ports.activity_data import FitActivityParser, ObjectStorage
from swim_coach.application.ports.repositories import UnitOfWorkFactory
from swim_coach.application.services.activity_data import ActivityDataService, ActivityDetail
from swim_coach.application.services.activity_views import activity_detail_v2
from swim_coach.application.services.heart_rate import aerobic_comparisons, main_block_heart_rate
from swim_coach.domain.activities.heart_rate import HeartRateFacts, valid_bpm
from swim_coach.domain.shared import EntityId, UserId
from swim_coach.domain.shared.errors import ResourceNotFoundError
from swim_coach.infrastructure.fit.heart_rate import fit_heart_rate
from swim_coach.infrastructure.fit.parser import GarminFitActivityParser


@pytest.mark.parametrize("value", [None, 0, 255, -1, True, "nan", "inf", "150.5", "bad"])
def test_invalid_hr_never_becomes_a_measurement(value: object) -> None:
    assert valid_bpm(value) is None


def test_fit_zones_preserve_indices_seconds_and_percent_denominator() -> None:
    hr = fit_heart_rate(
        {
            "avg_heart_rate": 142,
            "max_heart_rate": 170,
            "time_in_hr_zone": [10, 30, 60],
            "total_timer_time": 150,
        },
        {},
    )
    assert hr.avg_bpm == 142
    assert hr.max_bpm == 170
    assert [zone.zone_index for zone in hr.zones] == [0, 1, 2]
    assert [zone.percent_of_zone_time for zone in hr.zones] == ["10.00", "30.00", "60.00"]
    assert hr.zone_time_s == "100"
    assert "HR_ZONE_BOUNDARIES_UNAVAILABLE" in hr.warnings
    assert all(zone.high_boundary_bpm is None for zone in hr.zones)


def test_referenced_session_zones_do_not_pick_lap_or_another_session() -> None:
    hr = fit_heart_rate(
        {"message_index": 1},
        {
            "time_in_zone_mesgs": [
                {"reference_mesg": "lap", "reference_index": 1, "time_in_hr_zone": [99]},
                {"reference_mesg": "session", "reference_index": 0, "time_in_hr_zone": [88]},
                {
                    "reference_mesg": "session",
                    "reference_index": 1,
                    "time_in_hr_zone": [20, 30],
                    "hr_zone_high_boundary": [120, 150],
                },
            ]
        },
    )
    assert hr.zones_source == "FIT_TIME_IN_ZONE"
    assert hr.zone_time_s == "50"
    assert [zone.high_boundary_bpm for zone in hr.zones] == [120, 150]


@pytest.mark.parametrize("times", [[0, 0], [-1, 30], [None, 10], ["nan", 20], [1] * 17])
def test_missing_or_invalid_zone_time_never_invents_distribution(times: list[object]) -> None:
    hr = fit_heart_rate({"time_in_hr_zone": times}, {})
    assert hr.zones == ()
    assert hr.zone_time_s is None


def _view() -> dict:
    activity, normalized = _synthetic_activity_fixture()
    intervals = (
        replace(normalized.intervals[0], avg_hr_bpm=150, max_hr_bpm=170),
        normalized.intervals[1],
    )
    normalized = replace(normalized, intervals=intervals)
    return activity_detail_v2(ActivityDetail(activity, normalized, None, None, None))


def test_main_average_excludes_rest_and_reports_missing_hr_coverage() -> None:
    view = _view()
    rest = view["intervals"][1]
    rest["heart_rate"] = {"avg_bpm": 200, "max_bpm": 210}
    second = deepcopy(view["intervals"][0])
    second["index"] = 2
    second["durations"]["timer_s"] = "158.171"
    second["heart_rate"]["avg_bpm"] = None
    second["heart_rate"]["max_bpm"] = None
    view["intervals"].append(second)
    main = main_block_heart_rate(view)
    assert main["avg_bpm"] == "150.00"
    assert main["max_bpm"] == 170
    assert main["coverage_ratio"] == "0.50"
    assert len(main["blocks"]) == 2
    assert main["blocks"][1]["rest_before_s"] == "25.03"


def test_main_average_is_time_weighted_not_average_of_averages() -> None:
    view = _view()
    first = view["intervals"][0]
    first["durations"]["timer_s"] = "100"
    second = deepcopy(first)
    second["index"] = 2
    second["durations"]["timer_s"] = "300"
    second["heart_rate"]["avg_bpm"] = 170
    view["intervals"].append(second)
    assert main_block_heart_rate(view)["avg_bpm"] == "165.00"


def test_longer_repetition_at_same_pace_is_exploratory_evidence() -> None:
    current = _view()
    previous = deepcopy(current)
    block = current["main_set_heart_rate"]["blocks"][0]
    block["distance_m"] = 240
    block["pace_s_per_100m"] = "169.00"
    block["avg_bpm"] = 140
    prior = previous["main_set_heart_rate"]["blocks"][0]
    prior["distance_m"] = 160
    prior["pace_s_per_100m"] = "169.00"
    prior["avg_bpm"] = 150
    result = aerobic_comparisons(current, [previous])
    assert result["items"][0]["delta_avg_bpm"] == -10
    assert result["items"][0]["confidence"] == "LOW"
    assert "DIFFERENT_REPETITION_DISTANCE_AND_HR_RESPONSE_TIME" in result["items"][0]["reasons"]


@pytest.mark.parametrize("change", ["pool", "stroke", "pace_basis", "pace", "watch", "quality"])
def test_incomparable_or_disputed_measurements_do_not_produce_comparisons(change: str) -> None:
    current = _view()
    previous = deepcopy(current)
    block = previous["main_set_heart_rate"]["blocks"][0]
    if change == "pool":
        previous["pool"]["length_m"] = 25
    elif change == "stroke":
        block["stroke"] = "backstroke"
    elif change == "pace_basis":
        block["pace_basis"] = "timer"
    elif change == "pace":
        block["pace_s_per_100m"] = "200"
    elif change == "watch":
        previous["execution_evidence"]["performance_blocked"] = True
    else:
        previous["data_quality"]["level"] = "LOW"
    assert aerobic_comparisons(current, [previous])["items"] == []


def test_parser_and_public_view_keep_hr_facts_without_raw_payload() -> None:
    messages = _messages()
    messages["session_mesgs"][0].update(
        {
            "avg_heart_rate": 142,
            "max_heart_rate": 172,
            "time_in_hr_zone": [20, 40],
        }
    )
    activity, _ = _synthetic_activity_fixture()
    normalized = GarminFitActivityParser().normalize_messages(
        messages,
        user_id=activity.user_id,
        activity_id=activity.id,
        artifact_id=activity.raw_summary_id,
        input_checksum="a" * 64,
        fallback_pool_length_m=20,
    )
    hr = HeartRateFacts.model_validate(normalized.normalization.heart_rate)
    assert hr.avg_bpm == 142
    assert hr.zone_time_s == "60"
    public = activity_detail_v2(ActivityDetail(activity, normalized, None, None, None))
    assert public["heart_rate"]["max_bpm"] == 172
    assert public["raw_fit_exposed"] is False


def test_absent_fit_hr_uses_summary_with_explicit_source() -> None:
    activity, normalized = _synthetic_activity_fixture()
    activity = replace(activity, avg_hr=145, max_hr=175)
    view = activity_detail_v2(ActivityDetail(activity, normalized, None, None, None))
    assert view["heart_rate"]["avg_bpm"] == 145
    assert view["heart_rate"]["source"] == "GARMIN_SUMMARY"
    assert view["heart_rate"]["zones"] == []


@pytest.mark.asyncio
async def test_history_is_bounded_to_earlier_user_scoped_activity_reads() -> None:
    activity, normalized = _synthetic_activity_fixture()
    prior = replace(
        activity, id=EntityId.new(), start_time_utc=activity.start_time_utc - timedelta(days=21)
    )
    prior_normalized = replace(
        normalized, normalization=replace(normalized.normalization, activity_id=prior.id)
    )
    repository = SimpleNamespace(
        get_current_normalization=AsyncMock(return_value=prior_normalized),
        get_analysis=AsyncMock(return_value=None),
        get_feedback=AsyncMock(return_value=None),
    )
    activities = SimpleNamespace(list_recent=AsyncMock(return_value=[prior]))
    manager = AsyncMock()
    manager.__aenter__.return_value = SimpleNamespace(
        activities=activities, activity_data=repository
    )
    factory = MagicMock(return_value=manager)
    service = ActivityDataService(
        cast(UnitOfWorkFactory, factory),
        None,
        cast(ObjectStorage, object()),
        cast(FitActivityParser, object()),
    )
    detail = ActivityDetail(activity, normalized, None, None, None)
    view = _view()
    await service.heart_rate_comparisons(activity.user_id, detail, view)
    activities.list_recent.assert_awaited_once_with(
        activity.user_id, limit=20, before=activity.start_time_utc
    )
    repository.get_current_normalization.assert_awaited_once_with(activity.user_id, prior.id)
    repository.get_feedback.assert_awaited_once_with(activity.user_id, prior.id)
    factory.reset_mock()
    with pytest.raises(ResourceNotFoundError):
        await service.heart_rate_comparisons(UserId.new(), detail, view)
    factory.assert_not_called()


@pytest.mark.asyncio
async def test_no_current_hr_does_not_query_historical_details() -> None:
    activity, normalized = _synthetic_activity_fixture()
    factory = MagicMock()
    service = ActivityDataService(
        cast(UnitOfWorkFactory, factory),
        None,
        cast(ObjectStorage, object()),
        cast(FitActivityParser, object()),
    )
    detail = ActivityDetail(activity, normalized, None, None, None)
    result = await service.heart_rate_comparisons(
        activity.user_id, detail, activity_detail_v2(detail)
    )
    assert result["status"] == "INSUFFICIENT_COMPARABLE_DATA"
    factory.assert_not_called()
