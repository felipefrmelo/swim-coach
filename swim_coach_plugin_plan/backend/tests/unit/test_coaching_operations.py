from datetime import UTC, date, datetime, time

import pytest

from swim_coach.domain.shared.diagnostics import classify_failure
from swim_coach.domain.shared.errors import DomainError
from swim_coach.domain.shared.repair import schema_recovery
from swim_coach.domain.workouts import CanonicalWorkout, validate_workout
from swim_coach.domain.workouts.calendar import CalendarRequest, local_instant, resolve_calendar


def test_monday_november_2_resolves_this_week_without_shifting_a_week() -> None:
    reference = datetime(2026, 11, 2, 14, tzinfo=UTC)
    requests = [
        CalendarRequest(period="TOMORROW", weekday="TUESDAY"),
        CalendarRequest(period="THIS_WEEK", weekday="THURSDAY"),
    ]
    actual = [
        resolve_calendar(r, reference=reference, timezone="America/Sao_Paulo") for r in requests
    ]
    assert actual == [date(2026, 11, 3), date(2026, 11, 5)]
    assert resolve_calendar(
        CalendarRequest(period="NEXT_WEEK", weekday="TUESDAY"),
        reference=reference,
        timezone="America/Sao_Paulo",
    ) == date(2026, 11, 10)


@pytest.mark.parametrize(
    ("reference", "zone", "expected"),
    [
        (datetime(2026, 12, 31, 23, tzinfo=UTC), "UTC", date(2027, 1, 1)),
        (datetime(2026, 11, 3, 1, tzinfo=UTC), "America/Sao_Paulo", date(2026, 11, 3)),
        (datetime(2026, 11, 3, 1, tzinfo=UTC), "Asia/Tokyo", date(2026, 11, 4)),
        (datetime(2026, 10, 31, 23, tzinfo=UTC), "UTC", date(2026, 11, 1)),
    ],
)
def test_local_tomorrow_across_month_year_and_travel(reference, zone, expected) -> None:
    assert (
        resolve_calendar(CalendarRequest(period="TOMORROW"), reference=reference, timezone=zone)
        == expected
    )


@pytest.mark.parametrize("day", [date(2026, 3, 8), date(2026, 11, 1)])
def test_dst_gap_and_fold_require_an_explicit_unambiguous_time(day) -> None:
    with pytest.raises(DomainError, match="unambiguous"):
        local_instant(day, time(2, 30) if day.month == 3 else time(1, 30), "America/Vancouver")


def test_absolute_date_must_match_explicit_weekday() -> None:
    with pytest.raises(DomainError, match="disagree"):
        resolve_calendar(
            CalendarRequest(period="ABSOLUTE", local_date=date(2026, 11, 3), weekday="THURSDAY"),
            reference=datetime.now(UTC),
            timezone="UTC",
        )


def test_naive_reference_is_rejected() -> None:
    with pytest.raises(DomainError, match="offset"):
        resolve_calendar(
            CalendarRequest(period="TOMORROW"), reference=datetime(2026, 11, 2), timezone="UTC"
        )


def test_duration_includes_nested_pace_ranges_and_every_prescribed_rest() -> None:
    workout = CanonicalWorkout.model_validate(
        {
            "title": "Synthetic 1040 m",
            "purpose": "BASE",
            "pool_length_m": 20,
            "nodes": [
                {
                    "type": "repeat",
                    "repetitions": 4,
                    "children": [
                        {
                            "type": "step",
                            "end_condition": {"type": "distance", "meters": 260},
                            "target": {
                                "type": "pace_range",
                                "min_seconds_per_100m": 165,
                                "max_seconds_per_100m": 195,
                            },
                        },
                        {
                            "type": "step",
                            "step_role": "REST",
                            "end_condition": {"type": "time", "seconds": 30},
                        },
                    ],
                }
            ],
        }
    )
    totals = validate_workout(workout).totals
    assert totals.distance_m == 1040
    assert totals.estimated_total_seconds == 1992
    assert totals.duration_min_seconds == 1836
    assert totals.duration_max_seconds == 2148
    assert totals.duration_complete


def test_no_target_is_explicitly_incomplete_and_does_not_invent_a_pace() -> None:
    definition = CanonicalWorkout.model_validate(
        {
            "title": "Synthetic",
            "purpose": "BASE",
            "pool_length_m": 20,
            "nodes": [{"type": "step", "end_condition": {"type": "distance", "meters": 1000}}],
        }
    )
    validation = validate_workout(definition)
    assert validation.totals.unpaced_distance_m == 1000
    assert not validation.totals.duration_complete
    assert validation.totals.duration_max_seconds is None
    assert "DURATION_INCOMPLETE" in {w.code for w in validation.warnings}


@pytest.mark.parametrize(
    ("layer", "status", "source", "origin", "code"),
    [
        ("MCP", 403, "firewallCustom", 0, "EDGE_FIREWALL_BLOCKED"),
        ("MCP", 403, None, None, "MCP_PERMISSION_DENIED"),
        ("OAUTH", 403, None, None, "OAUTH_AUTHORIZATION_REQUIRED"),
        ("GARMIN", 403, None, None, "GARMIN_AUTH_REQUIRED"),
        ("BACKEND", 503, None, None, "BACKEND_UNAVAILABLE"),
        ("BACKEND", 422, None, None, "SCHEMA_INVALID"),
    ],
)
def test_failure_classification_requires_layer_evidence(
    layer, status, source, origin, code
) -> None:
    assert (
        classify_failure(
            http_status=status, layer=layer, security_source=source, origin_status=origin
        )
        == code
    )


def test_schema_repairs_name_the_precise_fields_and_do_not_echo_values() -> None:
    details = schema_recovery(
        [],
        {
            "definition": {
                "weeks": [
                    {
                        "sessions": [
                            {
                                "session_number": 1,
                                "max_duration_minutes": 45,
                                "workout": {"nodes": [{"role": "PRIVATE"}]},
                            }
                        ]
                    }
                ]
            }
        },
    )
    assert {i["path"] for i in details["issues"]} == {
        "definition.weeks[0].sessions[0].max_duration_minutes",
        "definition.weeks[0].sessions[0].workout.nodes[0].role",
    }
    assert "PRIVATE" not in str(details)
    assert details["recovery"]["max_automatic_retries"] == 1
