from sqlalchemy import inspect

from swim_coach.infrastructure.db import Database

from .conftest import MigrationRoundTrip


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
    }
    assert expected_tables <= round_trip.tables_after_upgrade
    assert expected_tables.isdisjoint(round_trip.tables_after_downgrade)

    database = Database(database_url)
    try:
        async with database.engine.connect() as connection:
            constraints = await connection.run_sync(
                lambda sync_connection: inspect(sync_connection).get_check_constraints("pool")
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

    assert revision == "000003"
    assert immutable_trigger == 1
    assert {item["name"] for item in constraints} >= {
        "ck_pool_length_positive",
        "ck_pool_version",
    }
