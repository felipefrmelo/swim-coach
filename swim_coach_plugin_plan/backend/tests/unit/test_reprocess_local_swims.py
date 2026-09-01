from datetime import UTC, datetime
from decimal import Decimal
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Protocol, cast

import pytest

from swim_coach.domain.garmin import Activity
from swim_coach.domain.shared import (
    Distance,
    DomainError,
    Duration,
    EntityId,
    PoolLength,
    UserId,
)


class _Remap(Protocol):
    def __call__(
        self, activity: Activity, payload: dict[str, object], timezone: str
    ) -> Activity: ...


class _ReprocessFit(Protocol):
    async def __call__(
        self, processor: Any, user_id: UserId, activity_id: EntityId
    ) -> str | None: ...


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts/reprocess_local_swims.py"
SPEC = spec_from_file_location("reprocess_local_swims", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
SCRIPT = module_from_spec(SPEC)
SPEC.loader.exec_module(SCRIPT)
_remap_activity_summary = cast(_Remap, SCRIPT._remap_activity_summary)
_reprocess_fit = cast(_ReprocessFit, SCRIPT._reprocess_fit)


def _activity() -> Activity:
    return Activity(
        id=EntityId.new(),
        user_id=UserId.new(),
        provider="garmin",
        external_activity_id="fixture-activity",
        name="Legacy",
        sport="swimming",
        subtype="lap_swimming",
        start_time_utc=datetime(2000, 1, 1, 12, 0, 0, tzinfo=UTC),
        timezone="UTC",
        distance=Distance(860),
        elapsed=Duration(Decimal("2089.629")),
        timer=Duration(Decimal("2075.559")),
        moving=Duration(Decimal("2075.559")),
        summary_checksum="a" * 64,
        raw_summary_id=EntityId.new(),
        pool_length=PoolLength(2_000),
        length_count=43,
        normalization_version="garmin-summary-v1",
    )


def _payload(**overrides: Any) -> dict[str, object]:
    value: dict[str, object] = {
        "activityId": "fixture-activity",
        "activityName": "Sanitized pool swim",
        "activityType": {"typeKey": "lap_swimming"},
        "startTimeGMT": "2000-01-01 12:00:00",
        "startTimeLocal": "2000-01-01 09:00:00",
        "distance": 860,
        "duration": 2075.559,
        "elapsedDuration": 2089.629,
        "movingDuration": 1699.541,
        "poolLength": 2000,
        "numberOfActiveLengths": 43,
    }
    value.update(overrides)
    return value


def test_local_raw_summary_remap_reapplies_source_adapter_without_fit() -> None:
    remapped = _remap_activity_summary(
        _activity(),
        _payload(),
        "America/Sao_Paulo",
    )

    assert remapped.pool_length == PoolLength(20)
    assert remapped.distance == Distance(860)
    assert remapped.elapsed == Duration(Decimal("2089.629"))
    assert remapped.timer == Duration(Decimal("2075.559"))
    assert remapped.moving == Duration(Decimal("1699.541"))
    assert remapped.timezone == "America/Sao_Paulo"
    assert remapped.normalization_version == "garmin-summary-v2"


def test_local_raw_summary_remap_rejects_cross_activity_payload() -> None:
    with pytest.raises(ValueError, match="external id"):
        _remap_activity_summary(
            _activity(),
            _payload(activityId="another-activity"),
            "America/Sao_Paulo",
        )


async def test_local_fit_batch_failure_is_scoped_to_one_activity(
    capsys: pytest.CaptureFixture[str],
) -> None:
    failed_id = EntityId.new()
    successful_id = EntityId.new()

    class _Processor:
        def __init__(self) -> None:
            self.calls: list[EntityId] = []

        async def process_local(self, _user_id: UserId, activity_id: EntityId) -> Any:
            self.calls.append(activity_id)
            if activity_id == failed_id:
                raise DomainError("FIT_PARSE_FAILED", "Synthetic corrupt FIT.")
            return SimpleNamespace(
                normalized=SimpleNamespace(
                    normalization=SimpleNamespace(parser_version="swim-coach:2.1.0")
                )
            )

    processor = _Processor()
    user_id = UserId.new()
    assert await _reprocess_fit(processor, user_id, failed_id) is None
    assert await _reprocess_fit(processor, user_id, successful_id) == "swim-coach:2.1.0"
    assert processor.calls == [failed_id, successful_id]
    output = capsys.readouterr().out
    assert f"{failed_id} skipped=FIT_PARSE_FAILED" in output
    assert f"{successful_id} reprocessed parser=swim-coach:2.1.0" in output
