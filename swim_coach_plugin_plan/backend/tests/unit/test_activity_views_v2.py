from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
import yaml
from jsonschema import Draft202012Validator

from swim_coach.application.ports.repositories import UnitOfWorkFactory
from swim_coach.application.services.activity_data import ActivityDataService, ActivityDetail
from swim_coach.application.services.activity_views import (
    activity_detail_v2,
    activity_summary_v2,
)
from swim_coach.application.services.context import ContextService
from swim_coach.application.services.identity import IdentityService
from swim_coach.application.services.mcp_read import (
    McpPrincipal,
    McpReadService,
)
from swim_coach.application.services.workouts import WorkoutService
from swim_coach.bootstrap.api import create_app
from swim_coach.domain.activities import (
    ActivityAnalysis,
    ActivityInterval,
    ActivityLength,
    ActivityNormalization,
    DataQuality,
    NormalizedActivity,
)
from swim_coach.domain.garmin import Activity
from swim_coach.domain.shared import (
    Distance,
    Duration,
    EntityId,
    PoolLength,
    UserId,
)
from swim_coach.interfaces.rest.activities import ActivityDetailResponse

ROOT = Path(__file__).resolve().parents[3]


def _synthetic_activity_fixture() -> tuple[Activity, NormalizedActivity]:
    user_id = UserId.new()
    activity_id = EntityId.new()
    normalization_id = EntityId.new()
    swim_interval_id = EntityId.new()
    rest_interval_id = EntityId.new()
    activity = Activity(
        id=activity_id,
        user_id=user_id,
        provider="garmin",
        external_activity_id="redacted-fixture",
        name="Pool swimming",
        sport="swimming",
        subtype="lap_swimming",
        start_time_utc=datetime(2000, 7, 1, 12, 0, 0, tzinfo=UTC),
        timezone="UTC",
        distance=Distance(860),
        elapsed=Duration(Decimal("2089.629")),
        timer=Duration(Decimal("2075.559")),
        moving=Duration(Decimal("1699.541")),
        summary_checksum="a" * 64,
        raw_summary_id=EntityId.new(),
        pool_length=PoolLength(20),
        length_count=43,
        avg_pace_seconds_per_100m=Decimal("241.344"),
    )
    intervals = (
        ActivityInterval(
            id=swim_interval_id,
            normalization_id=normalization_id,
            interval_index=0,
            interval_type="swim",
            start_offset_seconds=Decimal(0),
            duration_seconds=Decimal("158.171"),
            rest_seconds=Decimal(0),
            distance_m=80,
            elapsed_seconds=Decimal("158.171"),
            timer_seconds=Decimal("158.171"),
            moving_seconds=Decimal("135.200"),
            swim_seconds=Decimal("135.200"),
            stationary_seconds=Decimal("22.971"),
            garmin_reported_speed_m_per_s=Decimal("0.591716"),
            pace_from_garmin_reported_speed_seconds_per_100m=Decimal("169.000"),
            moving_pace_seconds_per_100m=Decimal("169.000"),
            swim_pace_seconds_per_100m=Decimal("169.000"),
            timer_pace_seconds_per_100m=Decimal("197.714"),
            elapsed_pace_seconds_per_100m=Decimal("197.714"),
            planned_role="work",
            detected_stroke="freestyle",
            provenance={"timer_seconds": {"source": "garmin", "raw_field": "lap.total_timer_time"}},
        ),
        ActivityInterval(
            id=rest_interval_id,
            normalization_id=normalization_id,
            interval_index=1,
            interval_type="rest",
            start_offset_seconds=Decimal("158.171"),
            duration_seconds=Decimal("25.028"),
            rest_seconds=Decimal("25.028"),
            distance_m=0,
            elapsed_seconds=Decimal("25.028"),
            timer_seconds=Decimal("25.028"),
            moving_seconds=Decimal(0),
            swim_seconds=Decimal(0),
            stationary_seconds=Decimal("25.028"),
            planned_role="rest",
            provenance={"interval_type": {"source": "planned_workout"}},
        ),
    )
    lengths = (
        ActivityLength(
            id=EntityId.new(),
            normalization_id=normalization_id,
            interval_id=swim_interval_id,
            length_index=0,
            distance_m=20,
            duration_seconds=Decimal("35.000"),
            detected_stroke="freestyle",
            length_type="active",
            moving_seconds=Decimal("32.000"),
            swim_seconds=Decimal("32.000"),
            rest_seconds=Decimal(0),
            garmin_reported_speed_m_per_s=Decimal("0.625"),
            pace_from_garmin_reported_speed_seconds_per_100m=Decimal("160.000"),
            moving_pace_seconds_per_100m=Decimal("160.000"),
            swim_pace_seconds_per_100m=Decimal("160.000"),
            timer_pace_seconds_per_100m=Decimal("175.000"),
            elapsed_pace_seconds_per_100m=Decimal("175.000"),
        ),
        ActivityLength(
            id=EntityId.new(),
            normalization_id=normalization_id,
            interval_id=rest_interval_id,
            length_index=1,
            distance_m=0,
            duration_seconds=Decimal("25.028"),
            length_type="idle",
        ),
    )
    normalization = ActivityNormalization(
        id=normalization_id,
        user_id=user_id,
        activity_id=activity_id,
        artifact_id=EntityId.new(),
        parser_version="garmin-fit:2.0.0",
        profile_version="garmin-fit-profile:21.208.0",
        input_checksum="b" * 64,
        pool_length_m=20,
        distance_m=860,
        elapsed_seconds=Decimal("2089.629"),
        timer_seconds=Decimal("2075.559"),
        moving_seconds=Decimal("1699.541"),
        active_length_count=43,
        completeness=Decimal("0.98"),
        quality=DataQuality.COMPLETE,
        swim_seconds=Decimal("1807.915"),
        rest_seconds=Decimal("267.644"),
        stationary_seconds=Decimal("108.374"),
        garmin_reported_speed_m_per_s=Decimal("0.591716"),
        pace_from_garmin_reported_speed_seconds_per_100m=Decimal("169.000"),
        moving_pace_seconds_per_100m=Decimal("197.621"),
        swim_pace_seconds_per_100m=Decimal("210.223"),
        timer_pace_seconds_per_100m=Decimal("241.344"),
        session_pace_seconds_per_100m=Decimal("242.980"),
        provenance={
            "pool_length_m": {
                "source": "garmin",
                "raw_field": "session.pool_length",
                "transformation": "FIT profile scaling to metres",
            }
        },
    )
    return activity, NormalizedActivity(normalization, (), intervals, lengths)


def _all_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        result = set(value)
        for key, item in value.items():
            # Provenance intentionally names raw/canonical fields to explain where
            # values came from; those names are metadata, not public metric aliases.
            if key != "provenance":
                result.update(_all_keys(item))
        return result
    if isinstance(value, list):
        return set().union(*(_all_keys(item) for item in value))
    return set()


def test_summary_v2_exposes_explicit_duration_pace_pool_and_timezone_concepts() -> None:
    activity, normalized = _synthetic_activity_fixture()

    result = activity_summary_v2(
        activity,
        normalized,
        timezone_name="America/Sao_Paulo",
    )

    assert result["started_at_utc"] == "2000-07-01T12:00:00+00:00"
    assert result["started_at_local"] == "2000-07-01T09:00:00-03:00"
    assert result["timezone"] == "America/Sao_Paulo"
    assert result["distance_m"] == 860
    assert result["pool"] == {"length_m": 20, "active_length_count": 43}
    assert result["durations"] == {
        "elapsed_s": "2089.629",
        "timer_s": "2075.559",
        "moving_s": "1699.541",
        "swim_s": "1807.915",
        "rest_s": "267.644",
        "stationary_s": "108.374",
    }
    assert result["speeds"] == {"garmin_reported_m_per_s": "0.591716"}
    assert result["paces"] == {
        "pace_from_garmin_reported_speed_s_per_100m": "169.000",
        "moving_s_per_100m": "197.621",
        "swim_s_per_100m": "210.223",
        "timer_s_per_100m": "241.344",
        "session_s_per_100m": "242.980",
    }
    assert result["data_quality"] == {"level": "HIGH", "reasons": []}
    assert result["provenance"]["pool_length_m"]["raw_field"] == "session.pool_length"


def test_summary_v2_replaces_invalid_iana_timezone_with_coherent_utc_fact() -> None:
    activity, normalized = _synthetic_activity_fixture()

    result = activity_summary_v2(activity, normalized, timezone_name="Mars/Olympus")

    assert result["timezone"] == "UTC"
    assert result["started_at_local"] == "2000-07-01T12:00:00+00:00"
    assert result["data_quality"] == {
        "level": "MEDIUM",
        "reasons": ["INVALID_TIMEZONE_FALLBACK_UTC"],
    }
    assert result["provenance"]["timezone"]["transformation"] == (
        "invalid IANA timezone replaced with UTC"
    )


def test_local_reprocess_never_reuses_legacy_2000m_pool_as_fit_fallback() -> None:
    activity, _ = _synthetic_activity_fixture()
    legacy = replace(activity, pool_length=PoolLength(2_000), length_count=43)

    assert ActivityDataService._fallback_pool_length_m(legacy) == 20


def test_missing_summary_pool_does_not_block_a_valid_fit_pool_fact() -> None:
    activity, _ = _synthetic_activity_fixture()
    summary_without_pool_evidence = replace(activity, pool_length=None, length_count=None)

    assert ActivityDataService._fallback_pool_length_m(summary_without_pool_evidence) is None


def test_unprocessed_v2_summary_discloses_inferred_source_provenance() -> None:
    activity, _ = _synthetic_activity_fixture()
    activity = replace(activity, normalization_version="garmin-summary-v2")

    result = activity_summary_v2(activity, timezone_name="America/Sao_Paulo")

    assert result["durations"]["moving_s"] is None
    assert result["paces"]["pace_from_garmin_reported_speed_s_per_100m"] is None
    assert result["provenance"]["pool_length_m"] == {
        "source": "inferred",
        "raw_field": "poolLength",
        "transformation": "activity-list poolLength / 100",
        "interpretation": "inferred",
        "source_endpoint": "/activitylist-service/activities/search/activities",
    }
    assert result["provenance"]["moving_duration_s"]["value_status"] == (
        "unavailable_until_canonical_fit_normalization"
    )
    assert result["provenance"]["garmin_summary_averagePace"]["value_status"] == (
        "preserved_private_not_normalized_to_pace"
    )


def test_detail_v2_keeps_rest_and_garmin_pace_distinct_from_timer_pace() -> None:
    activity, normalized = _synthetic_activity_fixture()

    result = activity_detail_v2(
        ActivityDetail(activity, normalized, None, None, None),
        timezone_name="America/Sao_Paulo",
    )

    assert result["schema_version"] == "2.0"
    assert result["normalization"]["parser_version"] == "garmin-fit:2.0.0"
    assert result["intervals"][0]["interval_type"] == "SWIM"
    assert result["intervals"][0]["planned_role"] == "WORK"
    assert (
        result["intervals"][0]["paces"]["pace_from_garmin_reported_speed_s_per_100m"] == "169.000"
    )
    assert result["intervals"][0]["speeds"]["garmin_reported_m_per_s"] == "0.591716"
    assert result["intervals"][0]["paces"]["timer_s_per_100m"] == "197.714"
    assert result["intervals"][1]["interval_type"] == "REST"
    assert result["intervals"][1]["distance_m"] == 0
    assert result["intervals"][1]["durations"]["rest_s"] == "25.028"
    assert result["lengths"][1]["length_type"] == "IDLE"
    assert result["lengths"][0]["speeds"]["garmin_reported_m_per_s"] == "0.625"
    assert result["lengths"][0]["paces"] == {
        "pace_from_garmin_reported_speed_s_per_100m": "160.000",
        "moving_s_per_100m": "160.000",
        "swim_s_per_100m": "160.000",
        "timer_s_per_100m": "175.000",
        "elapsed_s_per_100m": "175.000",
    }
    assert result["raw_fit_exposed"] is False

    ambiguous = {
        "started_local",
        "elapsed_seconds",
        "timer_seconds",
        "moving_seconds",
        "pace_seconds_per_100m",
        "pool_length_m",
        "duration_seconds",
        "rest_seconds",
        "stroke_type",
    }
    assert _all_keys(result).isdisjoint(ambiguous)


def test_analysis_views_use_positive_versioned_projections_and_drop_raw_injection() -> None:
    activity, normalized = _synthetic_activity_fixture()
    fact = normalized.normalization
    analysis = ActivityAnalysis(
        id=EntityId.new(),
        user_id=activity.user_id,
        activity_id=activity.id,
        normalization_id=fact.id,
        analysis_version="swim-analysis:2.0.0",
        parser_version=fact.parser_version,
        input_checksum=fact.input_checksum,
        pool_length_m=fact.pool_length_m,
        metrics={
            "average_pace_seconds_per_100m": "241.344",
            "best_interval_pace_seconds_per_100m": "169.000",
            "total_rest_seconds": "267.644",
            "consistency_cv": "0.043",
            "fade_percent": "-2.1",
            "completion_ratio": "0.977",
            "average_swolf": "49.55",
            "average_strokes_per_length": "10.02",
            "srpe_load": "242.15",
            "pool_length_m": 20,
            "raw_fit": {"records": ["private"]},
            "external_activity_id": "private-provider-id",
            "sets": [
                {
                    "key": {
                        "distance_m": 80,
                        "planned_intensity": "MODERATE",
                        "target_min_pace_s_per_100m": "165.0",
                        "target_max_pace_s_per_100m": "200.0",
                    },
                    "pace_basis": "moving",
                }
            ],
        },
        flags=(),
        quality=DataQuality.COMPLETE,
        summary={
            "headline": "Canonical analysis",
            "raw_payload": {"private": True},
        },
    )

    result = activity_detail_v2(
        ActivityDetail(activity, normalized, analysis, None, None),
        timezone_name="America/Sao_Paulo",
    )

    assert result["analysis"]["metrics"] == {
        "sets": [
            {
                "key": {
                    "distance_m": 80,
                    "planned_intensity": "MODERATE",
                    "target_min_pace_s_per_100m": "165.0",
                    "target_max_pace_s_per_100m": "200.0",
                },
                "pace_basis": "moving",
            }
        ]
    }
    assert result["analysis"]["summary"] == {"headline": "Canonical analysis"}
    assert _all_keys(result["analysis"]).isdisjoint(
        {"raw_fit", "raw_payload", "external_activity_id"}
    )

    legacy = ActivityDetailResponse.from_detail(
        ActivityDetail(activity, normalized, analysis, None, None)
    ).model_dump(mode="json")
    assert set(legacy["analysis"]["metrics"]) == {
        "average_pace_seconds_per_100m",
        "best_interval_pace_seconds_per_100m",
        "total_rest_seconds",
        "consistency_cv",
        "fade_percent",
        "completion_ratio",
        "average_swolf",
        "average_strokes_per_length",
        "srpe_load",
        "pool_length_m",
    }
    assert _all_keys(legacy["analysis"]).isdisjoint(
        {"raw_fit", "raw_payload", "external_activity_id", "sets"}
    )


def test_v2_rejects_legacy_current_normalization_instead_of_reusing_false_moving() -> None:
    activity, normalized = _synthetic_activity_fixture()
    legacy_activity = replace(
        activity,
        normalization_version="garmin-summary-v1",
        pool_length=PoolLength(2000),
    )
    legacy_fact = replace(
        normalized.normalization,
        parser_version="garmin-fit-sdk:21.208.0|swim-coach:1.0.0",
        moving_seconds=Decimal("2075.559"),
        swim_seconds=None,
        rest_seconds=None,
        stationary_seconds=None,
        moving_pace_seconds_per_100m=None,
        swim_pace_seconds_per_100m=None,
        timer_pace_seconds_per_100m=None,
        session_pace_seconds_per_100m=None,
        provenance={},
    )
    legacy = NormalizedActivity(
        legacy_fact,
        normalized.laps,
        normalized.intervals,
        normalized.lengths,
    )

    summary = activity_summary_v2(
        legacy_activity,
        legacy,
        timezone_name="America/Sao_Paulo",
    )
    detail = activity_detail_v2(
        ActivityDetail(legacy_activity, legacy, None, None, None),
        timezone_name="America/Sao_Paulo",
    )

    assert summary["durations"]["moving_s"] is None
    assert summary["durations"]["timer_s"] == "2075.559"
    assert summary["pool"]["length_m"] is None
    assert summary["data_quality"] == {
        "level": "LOW",
        "reasons": ["LEGACY_NORMALIZATION_NOT_CANONICAL_V2"],
    }
    assert detail["normalization"] is None
    assert detail["intervals"] == []
    assert detail["analysis"] is None


def test_rest_v2_routes_publish_typed_openapi_contracts() -> None:
    schema = create_app().openapi()

    list_schema = schema["paths"]["/api/v2/activities"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    detail_schema = schema["paths"]["/api/v2/activities/{activity_id}"]["get"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"]

    assert list_schema["items"]["$ref"] == "#/components/schemas/ActivitySummaryV2"
    assert detail_schema["$ref"] == "#/components/schemas/ActivityDetailV2"
    detail_properties = schema["components"]["schemas"]["ActivityDetailV2"]["properties"]
    assert detail_properties["schema_version"]["const"] == "2.0"
    assert detail_properties["raw_fit_exposed"]["const"] is False
    activity_path = schema["paths"]["/api/v2/activities/{activity_id}/process"]
    feedback_path = schema["paths"]["/api/v2/activities/{activity_id}/feedback"]
    match_path = schema["paths"]["/api/v2/activities/{activity_id}/match"]
    assert activity_path["post"]["responses"]["202"]
    assert feedback_path["put"]["responses"]["200"]
    assert match_path["put"]["responses"]["200"]


def test_checked_in_openapi_v2_is_closed_and_accepts_the_real_public_projection() -> None:
    activity, normalized = _synthetic_activity_fixture()
    fact = normalized.normalization
    analysis = ActivityAnalysis(
        id=EntityId.new(),
        user_id=activity.user_id,
        activity_id=activity.id,
        normalization_id=fact.id,
        analysis_version="swim-analysis:2.0.1",
        parser_version=fact.parser_version,
        input_checksum=fact.input_checksum,
        pool_length_m=fact.pool_length_m,
        metrics={"sets": []},
        flags=(),
        quality=DataQuality.COMPLETE,
        summary={"headline": "Canonical analysis"},
    )
    payload = activity_detail_v2(
        ActivityDetail(activity, normalized, analysis, None, None),
        timezone_name="America/Sao_Paulo",
    )
    contract = yaml.safe_load((ROOT / "contracts/openapi-skeleton.yaml").read_text())
    schema = contract["components"]["schemas"]["ActivityDetailV2"]
    validation_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "components": contract["components"],
        "$ref": "#/components/schemas/ActivityDetailV2",
    }

    Draft202012Validator.check_schema(validation_schema)
    Draft202012Validator(validation_schema).validate(payload)
    assert schema["additionalProperties"] is False
    assert "allOf" not in schema

    process = contract["paths"]["/v2/activities/{activity_id}/process"]["post"]
    feedback = contract["paths"]["/v2/activities/{activity_id}/feedback"]["put"]
    match = contract["paths"]["/v2/activities/{activity_id}/match"]["put"]
    assert {item["$ref"] for item in process["parameters"]} == {
        "#/components/parameters/ActivityId",
        "#/components/parameters/CsrfToken",
        "#/components/parameters/IdempotencyKey",
    }
    assert feedback["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/FeedbackRequest"
    }
    assert {item["$ref"] for item in match["parameters"]} == {
        "#/components/parameters/ActivityId",
        "#/components/parameters/CsrfToken",
    }
    assert match["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ManualMatchRequest"
    }


def test_v1_and_v2_interval_vocabularies_remain_versioned() -> None:
    activity, normalized = _synthetic_activity_fixture()
    legacy_work = replace(normalized.intervals[0], interval_type="work")
    detail = ActivityDetail(
        activity,
        NormalizedActivity(
            normalized.normalization,
            normalized.laps,
            (legacy_work, normalized.intervals[1]),
            normalized.lengths,
        ),
        None,
        None,
        None,
    )

    v1 = ActivityDetailResponse.from_detail(detail).model_dump(mode="json")
    v2 = activity_detail_v2(detail, timezone_name="America/Sao_Paulo")

    assert [item["interval_type"] for item in v1["intervals"]] == ["work", "rest"]
    assert [item["interval_type"] for item in v2["intervals"]] == ["SWIM", "REST"]


class _ActivityDataServiceStub:
    def __init__(self, detail: ActivityDetail) -> None:
        self._detail = detail

    async def get(self, user_id: UserId, activity_id: EntityId) -> ActivityDetail:
        assert user_id == self._detail.activity.user_id
        assert activity_id == self._detail.activity.id
        return self._detail


class _McpUnitOfWork:
    def __init__(
        self,
        activity: Activity,
        normalized: NormalizedActivity,
        analyses: tuple[ActivityAnalysis, ...] = (),
    ) -> None:
        self.users = SimpleNamespace(get=self._get_user)
        self.activities = SimpleNamespace(list_recent=self._list_recent)
        self.activity_data = SimpleNamespace(
            list_current_normalization_facts=self._list_current_normalization_facts,
            list_analyses=self._list_analyses,
        )
        self._activity = activity
        self._normalized = normalized
        self._analyses = analyses

    async def __aenter__(self) -> _McpUnitOfWork:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def _get_user(self, user_id: UserId) -> object:
        assert user_id == self._activity.user_id
        return SimpleNamespace(timezone="America/Sao_Paulo")

    async def _list_recent(self, user_id: UserId, **_: object) -> list[Activity]:
        assert user_id == self._activity.user_id
        return [self._activity]

    async def _list_current_normalization_facts(
        self, user_id: UserId, activity_ids: list[EntityId]
    ) -> list[ActivityNormalization]:
        assert user_id == self._activity.user_id
        assert activity_ids == [self._activity.id]
        return [self._normalized.normalization]

    async def _list_analyses(self, *_: object, **__: object) -> list[ActivityAnalysis]:
        return list(self._analyses)


class _McpUnitOfWorkFactory:
    def __init__(self, uow: _McpUnitOfWork) -> None:
        self._uow = uow

    def __call__(self) -> _McpUnitOfWork:
        return self._uow


@pytest.mark.asyncio
async def test_mcp_swims_use_v2_envelope_and_do_not_expose_ambiguous_or_raw_fields() -> None:
    activity, normalized = _synthetic_activity_fixture()
    fact = normalized.normalization
    analysis = ActivityAnalysis(
        id=EntityId.new(),
        user_id=activity.user_id,
        activity_id=activity.id,
        normalization_id=fact.id,
        analysis_version="swim-analysis:2.0.1",
        parser_version=fact.parser_version,
        input_checksum=fact.input_checksum,
        pool_length_m=fact.pool_length_m,
        metrics={
            "average_pace_seconds_per_100m": "241.344",
            "sets": [],
            "raw_fit": {"records": ["private"]},
            "external_activity_id": "private-provider-id",
        },
        flags=(),
        quality=DataQuality.COMPLETE,
        summary={"headline": "Canonical analysis", "raw_payload": {"private": True}},
    )
    detail = ActivityDetail(activity, normalized, analysis, None, None)
    uow = _McpUnitOfWork(activity, normalized, (analysis,))
    service = McpReadService(
        uow_factory=cast(UnitOfWorkFactory, _McpUnitOfWorkFactory(uow)),
        identity=cast(IdentityService, object()),
        context=cast(ContextService, object()),
        workouts=cast(WorkoutService, object()),
        activity_data=cast(ActivityDataService, _ActivityDataServiceStub(detail)),
    )
    principal = McpPrincipal(
        activity.user_id,
        "fixture",
        frozenset({"coach"}),
        timezone="America/Sao_Paulo",
    )

    recent = await service.list_recent_swims(
        principal,
        "request-list",
        limit=5,
        before=None,
        include_analysis_summary=True,
    )
    selected = await service.get_swim_activity(
        principal,
        "request-detail",
        activity_id=activity.id,
        include_intervals=True,
        include_lengths=True,
        max_intervals=50,
    )
    legacy = await service.get_swim_activity_v1(
        principal,
        "request-detail-v1",
        activity_id=activity.id,
        include_intervals=True,
        include_lengths=False,
        max_intervals=50,
    )

    assert recent.schema_version == "2.0"
    assert selected.schema_version == "2.0"
    assert recent.data["items"][0]["started_at_local"] == "2000-07-01T09:00:00-03:00"
    assert recent.data["items"][0]["timezone"] == "America/Sao_Paulo"
    assert selected.data["started_at_local"] == recent.data["items"][0]["started_at_local"]
    assert recent.data["items"][0]["pool"]["length_m"] == 20
    assert selected.data["durations"]["moving_s"] == "1699.541"
    assert selected.data["durations"]["timer_s"] == "2075.559"
    assert selected.human_summary == "Swim covered 860 m in 1699.541 moving seconds."
    assert len(selected.data["lengths"]) == 2
    assert selected.data["raw_fit_exposed"] is False
    assert [item["type"] for item in legacy.data["intervals"]] == ["work", "rest"]
    assert selected.data["analysis"]["metrics"] == {"sets": []}
    assert selected.data["analysis"]["summary"] == {"headline": "Canonical analysis"}
    assert legacy.data["analysis"] == {"average_pace_seconds_per_100m": "241.344"}
    assert _all_keys(recent.model_dump(mode="json")).isdisjoint(
        {"started_local", "moving_seconds", "pace_seconds_per_100m", "pool_length_m"}
    )
    assert _all_keys(selected.model_dump(mode="json")).isdisjoint(
        {
            "external_activity_id",
            "raw_fit",
            "input_checksum",
            "started_local",
            "moving_seconds",
            "pace_seconds_per_100m",
            "pool_length_m",
        }
    )


@pytest.mark.asyncio
async def test_mcp_v2_marks_legacy_normalization_as_partial() -> None:
    activity, normalized = _synthetic_activity_fixture()
    legacy_activity = replace(activity, normalization_version="garmin-summary-v1")
    legacy_fact = replace(
        normalized.normalization,
        parser_version="garmin-fit-sdk:21.208.0|swim-coach:1.0.0",
    )
    legacy_normalized = NormalizedActivity(
        legacy_fact,
        normalized.laps,
        normalized.intervals,
        normalized.lengths,
    )
    detail = ActivityDetail(legacy_activity, legacy_normalized, None, None, None)
    uow = _McpUnitOfWork(legacy_activity, legacy_normalized)
    service = McpReadService(
        uow_factory=cast(UnitOfWorkFactory, _McpUnitOfWorkFactory(uow)),
        identity=cast(IdentityService, object()),
        context=cast(ContextService, object()),
        workouts=cast(WorkoutService, object()),
        activity_data=cast(ActivityDataService, _ActivityDataServiceStub(detail)),
    )
    principal = McpPrincipal(
        activity.user_id,
        "fixture",
        frozenset({"coach"}),
        timezone="America/Sao_Paulo",
    )

    result = await service.get_swim_activity(
        principal,
        "request-legacy-normalization",
        activity_id=activity.id,
        include_intervals=True,
        include_lengths=True,
        max_intervals=50,
    )

    assert result.status == "PARTIAL"
    assert [(warning.code, warning.message) for warning in result.warnings] == [
        ("DATA_INCOMPLETE", "Canonical FIT normalization is unavailable.")
    ]
    assert result.data["normalization"] is None
    assert result.data["intervals"] == []
    assert result.data["lengths"] == []


@pytest.mark.asyncio
async def test_mcp_recent_swims_exposes_planned_vs_actual_summary() -> None:
    activity, normalized = _synthetic_activity_fixture()
    fact = normalized.normalization
    adherence = {
        "planned_distance_m": 880,
        "actual_distance_m": 860,
        "distance_difference_m": -20,
        "alignments": [],
    }
    analysis = ActivityAnalysis(
        id=EntityId.new(),
        user_id=activity.user_id,
        activity_id=activity.id,
        normalization_id=fact.id,
        analysis_version="swim-analysis:2.0.1",
        parser_version=fact.parser_version,
        input_checksum=fact.input_checksum,
        pool_length_m=fact.pool_length_m,
        metrics={"planned_vs_actual": adherence},
        flags=(),
        quality=DataQuality.PARTIAL,
        summary={},
    )
    detail = ActivityDetail(activity, normalized, analysis, None, None)
    uow = _McpUnitOfWork(activity, normalized, (analysis,))
    service = McpReadService(
        uow_factory=cast(UnitOfWorkFactory, _McpUnitOfWorkFactory(uow)),
        identity=cast(IdentityService, object()),
        context=cast(ContextService, object()),
        workouts=cast(WorkoutService, object()),
        activity_data=cast(ActivityDataService, _ActivityDataServiceStub(detail)),
    )
    principal = McpPrincipal(
        activity.user_id,
        "fixture",
        frozenset({"coach"}),
        timezone="America/Sao_Paulo",
    )

    result = await service.list_recent_swims(
        principal,
        "request-list-adherence",
        limit=5,
        before=None,
        include_analysis_summary=True,
    )

    assert result.data["items"][0]["analysis_summary"]["planned_vs_actual"] == {
        "planned_distance_m": 880,
        "actual_distance_m": 860,
        "distance_difference_m": -20,
    }


@pytest.mark.asyncio
async def test_mcp_v2_human_summary_uses_canonical_normalization_not_legacy_summary() -> None:
    activity, normalized = _synthetic_activity_fixture()
    stale_summary = replace(
        activity,
        distance=Distance(2_000),
        timer=Duration(Decimal("2700")),
        moving=Duration(Decimal("2700")),
    )
    detail = ActivityDetail(stale_summary, normalized, None, None, None)
    uow = _McpUnitOfWork(stale_summary, normalized)
    service = McpReadService(
        uow_factory=cast(UnitOfWorkFactory, _McpUnitOfWorkFactory(uow)),
        identity=cast(IdentityService, object()),
        context=cast(ContextService, object()),
        workouts=cast(WorkoutService, object()),
        activity_data=cast(ActivityDataService, _ActivityDataServiceStub(detail)),
    )
    principal = McpPrincipal(
        stale_summary.user_id,
        "fixture",
        frozenset({"coach"}),
        timezone="America/Sao_Paulo",
    )

    result = await service.get_swim_activity(
        principal,
        "request-canonical-summary",
        activity_id=stale_summary.id,
        include_intervals=False,
        include_lengths=False,
        max_intervals=50,
    )

    assert result.human_summary == "Swim covered 860 m in 1699.541 moving seconds."
    assert "2000" not in result.human_summary
    assert "2700" not in result.human_summary


@pytest.mark.asyncio
async def test_mcp_v2_human_summary_prefers_active_swim_time_when_fit_moving_is_absent() -> None:
    activity, normalized = _synthetic_activity_fixture()
    fit_fact = replace(
        normalized.normalization,
        moving_seconds=None,
        swim_seconds=Decimal("1699.541"),
        rest_seconds=Decimal("376.018"),
        stationary_seconds=None,
        moving_pace_seconds_per_100m=None,
        swim_pace_seconds_per_100m=Decimal("197.621"),
    )
    fit_normalized = NormalizedActivity(
        fit_fact,
        normalized.laps,
        normalized.intervals,
        normalized.lengths,
    )
    detail = ActivityDetail(activity, fit_normalized, None, None, None)
    service = McpReadService(
        uow_factory=cast(
            UnitOfWorkFactory,
            _McpUnitOfWorkFactory(_McpUnitOfWork(activity, fit_normalized)),
        ),
        identity=cast(IdentityService, object()),
        context=cast(ContextService, object()),
        workouts=cast(WorkoutService, object()),
        activity_data=cast(ActivityDataService, _ActivityDataServiceStub(detail)),
    )

    result = await service.get_swim_activity(
        McpPrincipal(
            activity.user_id,
            "fixture",
            frozenset({"coach"}),
            timezone="America/Sao_Paulo",
        ),
        "request-fit-swim-time",
        activity_id=activity.id,
        include_intervals=False,
        include_lengths=False,
        max_intervals=50,
    )

    assert result.human_summary == "Swim covered 860 m in 1699.541 swim seconds."
