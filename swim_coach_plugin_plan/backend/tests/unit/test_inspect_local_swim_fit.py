from datetime import UTC, datetime
from enum import Enum
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import Any, Protocol, cast


class _SafeMessages(Protocol):
    def __call__(
        self, value: object, *, message_name: str, include_timestamps: bool
    ) -> list[dict[str, Any]]: ...


class _SafeSummary(Protocol):
    def __call__(self, payload: dict[str, Any], *, include_timestamps: bool) -> dict[str, Any]: ...


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts/inspect_local_swim_fit.py"
SPEC = spec_from_file_location("inspect_local_swim_fit", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
SCRIPT = module_from_spec(SPEC)
SPEC.loader.exec_module(SCRIPT)
_safe_messages = cast(_SafeMessages, SCRIPT._safe_messages)
_safe_summary = cast(_SafeSummary, SCRIPT._safe_summary)


class _PrivateObject:
    def __str__(self) -> str:
        return "private-object-value"


class _SafeEnum(Enum):
    ACTIVE = "active"


def test_fit_debug_projection_is_allowlisted_and_redacts_timestamps_by_default() -> None:
    result = _safe_messages(
        [
            {
                "sport": "swimming",
                "sub_sport": "lap_swimming",
                "start_time": datetime(2000, 7, 1, 12, 0, tzinfo=UTC),
                "pool_length": 20,
                "total_distance": 860,
                "enhanced_avg_speed": 0.506,
                "workout_rpe": 30,
                "workout_feel": 75,
                "start_position_lat": 123456,
                "start_position_long": -654321,
                "sport_profile_name": "Clube privado",
                "avg_heart_rate": 148,
                "future_sdk_payload": {"private": "value"},
            }
        ],
        message_name="session_mesgs",
        include_timestamps=False,
    )

    assert result == [
        {
            "sport": "swimming",
            "sub_sport": "lap_swimming",
            "start_time": "<timestamp-redacted>",
            "pool_length": 20,
            "total_distance": 860,
            "enhanced_avg_speed": 0.506,
            "workout_rpe": 30,
            "workout_feel": 75,
        }
    ]


def test_fit_debug_projection_excludes_user_defined_workout_step_names() -> None:
    result = _safe_messages(
        [
            {
                "message_index": 2,
                "duration_type": "time",
                "duration_value": 25,
                "intensity": "rest",
                "wkt_step_name": "Recuperação no clube do bairro",
                "notes": "dado pessoal não revisado",
            }
        ],
        message_name="workout_step_mesgs",
        include_timestamps=False,
    )

    assert result == [
        {
            "message_index": 2,
            "duration_type": "time",
            "duration_value": 25,
            "intensity": "rest",
        }
    ]


def test_fit_debug_projection_denies_unknown_message_types_and_string_timestamps() -> None:
    assert (
        _safe_messages(
            [{"future_private_field": "secret"}],
            message_name="future_mesgs",
            include_timestamps=False,
        )
        == []
    )
    assert _safe_messages(
        [{"start_time": "2000-07-01T12:00:00Z", "total_distance": 860}],
        message_name="session_mesgs",
        include_timestamps=False,
    ) == [{"start_time": "<timestamp-redacted>", "total_distance": 860}]


def test_fit_debug_projection_redacts_unknown_runtime_types_and_bounds_lists() -> None:
    result = _safe_messages(
        [
            {
                "sport": _PrivateObject(),
                "sub_sport": _SafeEnum.ACTIVE,
                "total_distance": list(range(150)),
            }
        ],
        message_name="session_mesgs",
        include_timestamps=False,
    )

    assert result[0]["sport"] == "<unsupported-redacted>"
    assert result[0]["sub_sport"] == "active"
    assert result[0]["total_distance"] == list(range(100))


def test_summary_debug_projection_is_allowlisted_and_omits_identity() -> None:
    result = _safe_summary(
        {
            "activityId": "private-garmin-id",
            "activityName": "Nome do clube privado",
            "activityType": {"typeKey": "lap_swimming", "future": "private"},
            "startTimeGMT": "2000-07-01 12:00:00",
            "startTimeLocal": "2000-07-01 09:00:00",
            "distance": 860,
            "duration": 2075.559,
            "poolLength": 2000,
            "future_private_field": "secret",
            "_swim_coach_semantics": {
                "provenance": {
                    "pool_length_m": {
                        "raw_field": "poolLength",
                        "transformation": "poolLength / 100",
                    }
                },
                "warnings": ["GARMIN_SUMMARY_POOL_LENGTH_UNIT_INFERRED"],
                "athlete_timezone": "America/Sao_Paulo",
                "expected_local_wall": "2000-07-01T09:00:00",
            },
        },
        include_timestamps=False,
    )

    assert result == {
        "activityType": {"typeKey": "lap_swimming"},
        "startTimeGMT": "<timestamp-redacted>",
        "startTimeLocal": "<timestamp-redacted>",
        "distance": 860,
        "duration": 2075.559,
        "poolLength": 2000,
        "_swim_coach_semantics": {
            "provenance": {
                "pool_length_m": {
                    "raw_field": "poolLength",
                    "transformation": "poolLength / 100",
                }
            },
            "warnings": ["GARMIN_SUMMARY_POOL_LENGTH_UNIT_INFERRED"],
            "athlete_timezone": "America/Sao_Paulo",
            "expected_local_wall": "<timestamp-redacted>",
        },
    }
