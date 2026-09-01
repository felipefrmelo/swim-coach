import asyncio
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import delete, inspect, text
from sqlalchemy.exc import DBAPIError

from swim_coach.infrastructure.db import Database
from swim_coach.infrastructure.db.models import (
    ActivityModel,
    ActivityNormalizationModel,
    AppUserModel,
    FileArtifactModel,
    RawProviderPayloadModel,
)

from .conftest import MigrationRoundTrip

ROOT = Path(__file__).resolve().parents[3]


async def test_migration_up_down_up_and_constraints(
    postgres_database: tuple[str, MigrationRoundTrip],
) -> None:
    database_url, round_trip = postgres_database
    expected_tables = {
        "app_user",
        "auth_identity",
        "athlete_profile",
        "athlete_constraint",
        "pool",
        "availability_rule",
        "device",
        "training_goal",
        "goal_milestone",
        "job",
        "outbox_event",
        "audit_event",
        "api_idempotency_record",
        "web_session",
        "oidc_login_attempt",
        "garmin_connection",
        "sync_cursor",
        "sync_run",
        "raw_provider_payload",
        "activity",
        "activity_import",
        "workout_template",
        "planned_workout",
        "workout_revision",
        "workout_schedule",
        "action_proposal",
        "action_approval",
        "action_execution",
        "external_workout_binding",
        "file_artifact",
        "activity_normalization",
        "activity_lap",
        "activity_interval",
        "activity_length",
        "activity_analysis",
        "workout_execution_match",
        "session_feedback",
        "mcp_tool_invocation",
        "training_rule_set",
        "planning_run",
        "training_decision",
        "notification",
        "data_export",
        "deletion_request",
    }
    assert expected_tables <= round_trip.tables_after_upgrade
    assert expected_tables.isdisjoint(round_trip.tables_after_downgrade)

    database = Database(database_url)
    try:
        async with database.engine.connect() as connection:
            constraints = await connection.run_sync(
                lambda sync_connection: inspect(sync_connection).get_check_constraints("pool")
            )
            canonical_columns = await connection.run_sync(
                lambda sync_connection: {
                    table: {
                        column["name"] for column in inspect(sync_connection).get_columns(table)
                    }
                    for table in (
                        "activity_normalization",
                        "activity_lap",
                        "activity_interval",
                        "activity_length",
                    )
                }
            )
            feedback_columns = await connection.run_sync(
                lambda sync_connection: {
                    column["name"]: column
                    for column in inspect(sync_connection).get_columns("session_feedback")
                }
            )
            normalization_constraints = await connection.run_sync(
                lambda sync_connection: inspect(sync_connection).get_check_constraints(
                    "activity_normalization"
                )
            )
            feedback_constraints = await connection.run_sync(
                lambda sync_connection: inspect(sync_connection).get_check_constraints(
                    "session_feedback"
                )
            )
            revision = (
                await connection.exec_driver_sql("SELECT version_num FROM alembic_version")
            ).scalar_one()
            immutable_trigger = (
                await connection.exec_driver_sql(
                    "SELECT count(*) FROM pg_trigger "
                    "WHERE tgname = 'trg_workout_revision_immutable' AND NOT tgisinternal"
                )
            ).scalar_one()
    finally:
        await database.dispose()

        assert revision == "000013"
    assert immutable_trigger == 1
    assert {item["name"] for item in constraints} >= {
        "ck_pool_length_positive",
        "ck_pool_version",
    }
    assert all("garmin_reported_speed_m_per_s" in columns for columns in canonical_columns.values())
    assert {"perceived_effort_rpe", "feeling_score"} <= canonical_columns["activity_normalization"]
    assert feedback_columns["rpe"]["nullable"] is True
    assert "feeling_score" in feedback_columns
    assert {item["name"] for item in normalization_constraints} >= {
        "ck_activity_normalization_rpe",
        "ck_activity_normalization_feeling",
    }
    assert {item["name"] for item in feedback_constraints} >= {
        "ck_session_feedback_rpe",
        "ck_session_feedback_feeling_score",
    }


async def test_canonical_v2_upgrade_repairs_only_corroborated_legacy_summary(
    postgres_database: tuple[str, MigrationRoundTrip],
) -> None:
    database_url, _ = postgres_database
    config = Config(str(ROOT / "backend/alembic.ini"))
    config.attributes["database_url"] = database_url
    database = Database(database_url)
    now = datetime(2000, 1, 1, 12, 0, 0, tzinfo=UTC)
    user_id = uuid4()
    raw_id = uuid4()
    activity_id = uuid4()
    try:
        async with database.engine.begin() as connection:
            await connection.exec_driver_sql("TRUNCATE TABLE app_user CASCADE")
        await asyncio.to_thread(command.downgrade, config, "000011")
        async with database.session_factory.begin() as session:
            await session.execute(
                text(
                    "INSERT INTO app_user "
                    "(id,email,display_name,locale,timezone,status,created_at,updated_at,version) "
                    "VALUES (:id,:email,'Summary migration','pt-BR','America/Sao_Paulo',"
                    "'active',:now,:now,1)"
                ),
                {"id": user_id, "email": f"summary-migration-{user_id}@example.test", "now": now},
            )
            await session.execute(
                text(
                    "INSERT INTO raw_provider_payload "
                    "(id,user_id,provider,entity_type,external_id,content_type,json_payload,"
                    "checksum,received_at) VALUES (:id,:user_id,'garmin','activity_summary',"
                    ":external_id,'application/json',CAST(:json_payload AS jsonb),"
                    ":checksum,:now)"
                ),
                {
                    "id": raw_id,
                    "user_id": user_id,
                    "external_id": str(activity_id),
                    "json_payload": json.dumps(
                        {"poolLength": 2_000, "numberOfActiveLengths": 43, "distance": 860}
                    ),
                    "checksum": "a" * 64,
                    "now": now,
                },
            )
            await session.execute(
                text(
                    "INSERT INTO activity "
                    "(id,user_id,provider,external_activity_id,name,sport,subtype,start_time_utc,"
                    "timezone,distance_m,elapsed_seconds,timer_seconds,moving_seconds,pool_length_m,"
                    "length_count,normalization_version,raw_summary_id,summary_checksum,created_at,"
                    "updated_at,version) VALUES (:id,:user_id,'garmin',:external_id,"
                    "'Legacy 860 m fixture','swimming','lap_swimming',:now,'UTC',860,2089.629,"
                    "2075.559,1699.541,2000,43,'garmin-summary-v1',:raw_id,:checksum,:now,:now,1)"
                ),
                {
                    "id": activity_id,
                    "user_id": user_id,
                    "external_id": str(activity_id),
                    "raw_id": raw_id,
                    "checksum": "b" * 64,
                    "now": now,
                },
            )

        await asyncio.to_thread(command.upgrade, config, "head")

        async with database.session_factory() as session:
            activity = await session.get(ActivityModel, activity_id)
            raw = await session.get(RawProviderPayloadModel, raw_id)
            assert activity is not None
            assert activity.pool_length_m == 20
            assert activity.timezone == "America/Sao_Paulo"
            assert activity.normalization_version == "garmin-summary-v2"
            assert raw is not None
            assert raw.json_payload["poolLength"] == 2_000
    finally:
        await asyncio.to_thread(command.upgrade, config, "head")
        async with database.engine.begin() as connection:
            await connection.exec_driver_sql("TRUNCATE TABLE app_user CASCADE")
        await database.dispose()


async def test_canonical_v2_downgrade_refuses_to_destroy_persisted_facts(
    postgres_database: tuple[str, MigrationRoundTrip],
) -> None:
    database_url, _ = postgres_database
    database = Database(database_url)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    user_id = uuid4()
    raw_id = uuid4()
    activity_id = uuid4()
    artifact_id = uuid4()
    normalization_id = uuid4()
    feedback_id = uuid4()
    try:
        async with database.session_factory.begin() as session:
            session.add(
                AppUserModel(
                    id=user_id,
                    email=f"migration-{user_id}@example.test",
                    display_name="Migration test",
                    locale="pt-BR",
                    timezone="America/Sao_Paulo",
                    status="active",
                    created_at=now,
                    updated_at=now,
                    version=1,
                )
            )
            await session.flush()
            session.add(
                RawProviderPayloadModel(
                    id=raw_id,
                    user_id=user_id,
                    provider="garmin",
                    entity_type="activity_summary",
                    external_id=str(activity_id),
                    content_type="application/json",
                    json_payload={},
                    checksum="a" * 64,
                    received_at=now,
                )
            )
            await session.flush()
            session.add(
                ActivityModel(
                    id=activity_id,
                    user_id=user_id,
                    provider="garmin",
                    external_activity_id=str(activity_id),
                    name="Migration fixture",
                    sport="swimming",
                    subtype="lap_swimming",
                    start_time_utc=now,
                    timezone="America/Sao_Paulo",
                    distance_m=20,
                    elapsed_seconds=Decimal("30"),
                    timer_seconds=Decimal("30"),
                    moving_seconds=Decimal("25"),
                    pool_length_m=20,
                    length_count=1,
                    raw_summary_id=raw_id,
                    summary_checksum="b" * 64,
                    created_at=now,
                    updated_at=now,
                    version=1,
                )
            )
            await session.flush()
            session.add(
                FileArtifactModel(
                    id=artifact_id,
                    user_id=user_id,
                    activity_id=activity_id,
                    provider="garmin",
                    artifact_type="fit",
                    storage_key=f"migration/{artifact_id}.fit",
                    content_type="application/vnd.ant.fit",
                    size_bytes=1,
                    checksum="c" * 64,
                    source_external_id_hash="d" * 64,
                    created_at=now,
                )
            )
            await session.flush()
            session.add(
                ActivityNormalizationModel(
                    id=normalization_id,
                    user_id=user_id,
                    activity_id=activity_id,
                    artifact_id=artifact_id,
                    parser_version="garmin-fit-sdk:test|swim-coach:2.0.0",
                    profile_version="test",
                    input_checksum="e" * 64,
                    pool_length_m=20,
                    distance_m=20,
                    elapsed_seconds=Decimal("30"),
                    timer_seconds=Decimal("30"),
                    moving_seconds=None,
                    active_length_count=1,
                    completeness=Decimal("0.8"),
                    quality="complete",
                    warnings_json=["MOVING_DURATION_UNAVAILABLE"],
                    provenance_json={},
                    created_at=now,
                )
            )

        config = Config(str(ROOT / "backend/alembic.ini"))
        config.attributes["database_url"] = database_url
        async with database.engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE activity_normalization "
                    "SET perceived_effort_rpe=3.0, feeling_score=75 WHERE id=:id"
                ),
                {"id": normalization_id},
            )
        with pytest.raises(DBAPIError, match="000013 downgrade is unsafe"):
            await asyncio.to_thread(command.downgrade, config, "000012")
        assert await database.revision() == "000013"
        async with database.engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE activity_normalization "
                    "SET perceived_effort_rpe=NULL, feeling_score=NULL WHERE id=:id"
                ),
                {"id": normalization_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO session_feedback "
                    "(id,user_id,activity_id,rpe,feeling_score,pain_present,created_at,"
                    "updated_at,version) VALUES "
                    "(:id,:user_id,:activity_id,NULL,75,false,:now,:now,1)"
                ),
                {
                    "id": feedback_id,
                    "user_id": user_id,
                    "activity_id": activity_id,
                    "now": now,
                },
            )
        with pytest.raises(DBAPIError, match="000013 downgrade is unsafe"):
            await asyncio.to_thread(command.downgrade, config, "000012")
        assert await database.revision() == "000013"
        async with database.engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM session_feedback WHERE id=:id"), {"id": feedback_id}
            )
        with pytest.raises(DBAPIError, match="downgrade is unsafe"):
            await asyncio.to_thread(command.downgrade, config, "000011")

        # Alembic rolls the multi-revision downgrade back atomically when the
        # canonical-v2 guard rejects the following step.
        assert await database.revision() == "000013"
        async with database.engine.connect() as connection:
            stored = (
                await connection.execute(
                    text(
                        "SELECT moving_seconds, warnings_json "
                        "FROM activity_normalization WHERE id=:id"
                    ),
                    {"id": normalization_id},
                )
            ).one()
            assert stored.moving_seconds is None
            assert stored.warnings_json == ["MOVING_DURATION_UNAVAILABLE"]
    finally:
        config = Config(str(ROOT / "backend/alembic.ini"))
        config.attributes["database_url"] = database_url
        await asyncio.to_thread(command.upgrade, config, "head")
        async with database.session_factory.begin() as session:
            await session.execute(
                delete(ActivityNormalizationModel).where(
                    ActivityNormalizationModel.id == normalization_id
                )
            )
            await session.execute(
                delete(FileArtifactModel).where(FileArtifactModel.id == artifact_id)
            )
            await session.execute(delete(ActivityModel).where(ActivityModel.id == activity_id))
            await session.execute(
                delete(RawProviderPayloadModel).where(RawProviderPayloadModel.id == raw_id)
            )
            await session.execute(delete(AppUserModel).where(AppUserModel.id == user_id))
        await database.dispose()


async def test_canonical_v2_preserves_and_downgrades_legacy_moving_fact(
    postgres_database: tuple[str, MigrationRoundTrip],
) -> None:
    database_url, _ = postgres_database
    config = Config(str(ROOT / "backend/alembic.ini"))
    config.attributes["database_url"] = database_url
    database = Database(database_url)
    now = datetime(2026, 1, 2, tzinfo=UTC)
    user_id = uuid4()
    raw_id = uuid4()
    activity_id = uuid4()
    artifact_id = uuid4()
    normalization_id = uuid4()
    try:
        async with database.engine.begin() as connection:
            await connection.exec_driver_sql("TRUNCATE TABLE app_user CASCADE")
        await asyncio.to_thread(command.downgrade, config, "000011")
        async with database.session_factory.begin() as session:
            await session.execute(
                text(
                    "INSERT INTO app_user "
                    "(id,email,display_name,locale,timezone,status,created_at,updated_at,version) "
                    "VALUES (:id,:email,'Legacy moving','pt-BR','America/Sao_Paulo','active',"
                    ":now,:now,1)"
                ),
                {"id": user_id, "email": f"legacy-moving-{user_id}@example.test", "now": now},
            )
            await session.execute(
                text(
                    "INSERT INTO raw_provider_payload "
                    "(id,user_id,provider,entity_type,external_id,content_type,json_payload,"
                    "checksum,received_at) VALUES (:id,:user_id,'garmin','activity_summary',"
                    ":external_id,'application/json','{}'::jsonb,:checksum,:now)"
                ),
                {
                    "id": raw_id,
                    "user_id": user_id,
                    "external_id": str(activity_id),
                    "checksum": "a" * 64,
                    "now": now,
                },
            )
            await session.execute(
                text(
                    "INSERT INTO activity "
                    "(id,user_id,provider,external_activity_id,name,sport,subtype,start_time_utc,"
                    "timezone,distance_m,elapsed_seconds,timer_seconds,moving_seconds,pool_length_m,"
                    "length_count,normalization_version,raw_summary_id,summary_checksum,created_at,"
                    "updated_at,version) VALUES (:id,:user_id,'garmin',:external_id,'Legacy',"
                    "'swimming','lap_swimming',:now,'UTC',20,35,30,30,20,1,'garmin-summary-v1',"
                    ":raw_id,:checksum,:now,:now,1)"
                ),
                {
                    "id": activity_id,
                    "user_id": user_id,
                    "external_id": str(activity_id),
                    "raw_id": raw_id,
                    "checksum": "b" * 64,
                    "now": now,
                },
            )
            await session.execute(
                text(
                    "INSERT INTO file_artifact "
                    "(id,user_id,activity_id,provider,artifact_type,storage_key,content_type,"
                    "size_bytes,checksum,source_external_id_hash,created_at) VALUES "
                    "(:id,:user_id,:activity_id,'garmin','fit',:storage_key,"
                    "'application/vnd.ant.fit',1,:checksum,:source_hash,:now)"
                ),
                {
                    "id": artifact_id,
                    "user_id": user_id,
                    "activity_id": activity_id,
                    "storage_key": f"legacy/{artifact_id}.fit",
                    "checksum": "c" * 64,
                    "source_hash": "d" * 64,
                    "now": now,
                },
            )
            await session.execute(
                text(
                    "INSERT INTO activity_normalization "
                    "(id,user_id,activity_id,artifact_id,parser_version,profile_version,"
                    "input_checksum,pool_length_m,distance_m,elapsed_seconds,timer_seconds,"
                    "moving_seconds,active_length_count,completeness,quality,warnings_json,"
                    "created_at) VALUES (:id,:user_id,:activity_id,:artifact_id,"
                    "'garmin-fit-sdk:test|swim-coach:1.0.0','test',:checksum,20,20,35,30,30,1,"
                    "1,'complete','[]'::jsonb,:now)"
                ),
                {
                    "id": normalization_id,
                    "user_id": user_id,
                    "activity_id": activity_id,
                    "artifact_id": artifact_id,
                    "checksum": "e" * 64,
                    "now": now,
                },
            )
            await session.execute(
                text("UPDATE activity SET current_normalization_id=:normalization_id WHERE id=:id"),
                {"normalization_id": normalization_id, "id": activity_id},
            )

        await asyncio.to_thread(command.upgrade, config, "head")
        async with database.engine.connect() as connection:
            moving_after_upgrade = await connection.scalar(
                text("SELECT moving_seconds FROM activity_normalization WHERE id=:id"),
                {"id": normalization_id},
            )
        assert moving_after_upgrade == Decimal("30.000")

        await asyncio.to_thread(command.downgrade, config, "000011")
        async with database.engine.connect() as connection:
            moving_after_downgrade = await connection.scalar(
                text("SELECT moving_seconds FROM activity_normalization WHERE id=:id"),
                {"id": normalization_id},
            )
        assert moving_after_downgrade == Decimal("30.000")
    finally:
        await asyncio.to_thread(command.upgrade, config, "head")
        async with database.engine.begin() as connection:
            await connection.exec_driver_sql("TRUNCATE TABLE app_user CASCADE")
        await database.dispose()
