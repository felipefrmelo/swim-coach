"""Canonical v2 swimming durations, paces, classification and provenance.

Revision ID: 000012
Revises: 000011
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "000012"
down_revision: str | None = "000011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NUMERIC = sa.Numeric(14, 3)
SPEED_NUMERIC = sa.Numeric(18, 9)


def _add_paces(table: str, *, elapsed_name: str) -> None:
    for name in (
        "pace_from_garmin_reported_speed_seconds_per_100m",
        "moving_pace_seconds_per_100m",
        "swim_pace_seconds_per_100m",
        "timer_pace_seconds_per_100m",
        elapsed_name,
    ):
        op.add_column(table, sa.Column(name, NUMERIC, nullable=True))


def _drop_paces(table: str, *, elapsed_name: str) -> None:
    for name in reversed(
        (
            "pace_from_garmin_reported_speed_seconds_per_100m",
            "moving_pace_seconds_per_100m",
            "swim_pace_seconds_per_100m",
            "timer_pace_seconds_per_100m",
            elapsed_name,
        )
    ):
        op.drop_column(table, name)


def upgrade() -> None:
    # Garmin Connect summary v1 stored the endpoint's observed hundredths-of-a-
    # metre value directly in a metre column and hard-coded UTC.  Repair only
    # rows whose independent distance/active-length relationship proves the
    # conversion. Unresolved summaries remain visible in v2 as degraded,
    # low-quality summary facts with ambiguous canonical values left null.
    op.execute(
        """
        UPDATE activity AS activity_row
        SET timezone = app_user.timezone,
            updated_at = now(),
            version = activity_row.version + 1
        FROM app_user
        WHERE activity_row.user_id = app_user.id
          AND activity_row.normalization_version = 'garmin-summary-v1'
          AND activity_row.timezone IS DISTINCT FROM app_user.timezone
        """
    )
    op.execute(
        """
        UPDATE activity
        SET pool_length_m = pool_length_m / 100,
            normalization_version = 'garmin-summary-v2',
            updated_at = now(),
            version = version + 1
        WHERE normalization_version = 'garmin-summary-v1'
          AND pool_length_m IS NOT NULL
          AND pool_length_m > 0
          AND pool_length_m % 100 = 0
          AND length_count IS NOT NULL
          AND length_count > 0
          AND (pool_length_m / 100) * length_count = distance_m
        """
    )
    op.alter_column("activity_normalization", "moving_seconds", nullable=True)
    for name in ("swim_seconds", "rest_seconds", "stationary_seconds"):
        op.add_column("activity_normalization", sa.Column(name, NUMERIC, nullable=True))
    op.add_column(
        "activity_normalization",
        sa.Column("garmin_reported_speed_m_per_s", SPEED_NUMERIC, nullable=True),
    )
    _add_paces("activity_normalization", elapsed_name="session_pace_seconds_per_100m")
    op.add_column(
        "activity_normalization",
        sa.Column(
            "provenance_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    # Keep parser-v1 moving_seconds physically intact for old binaries and a
    # legacy-only downgrade. The v2 repository masks this known timer alias at
    # read time and attaches explicit warning/provenance without destroying the
    # frozen v1 fact.
    op.drop_constraint(
        "ck_activity_normalization_durations", "activity_normalization", type_="check"
    )
    op.create_check_constraint(
        "ck_activity_normalization_durations",
        "activity_normalization",
        "elapsed_seconds >= 0 AND timer_seconds >= 0 "
        "AND (moving_seconds IS NULL OR moving_seconds >= 0) "
        "AND (swim_seconds IS NULL OR swim_seconds >= 0) "
        "AND (rest_seconds IS NULL OR rest_seconds >= 0) "
        "AND (stationary_seconds IS NULL OR stationary_seconds >= 0)",
    )
    op.create_check_constraint(
        "ck_activity_normalization_paces",
        "activity_normalization",
        "(garmin_reported_speed_m_per_s IS NULL OR garmin_reported_speed_m_per_s >= 0) "
        "AND (pace_from_garmin_reported_speed_seconds_per_100m IS NULL OR "
        "pace_from_garmin_reported_speed_seconds_per_100m >= 0) "
        "AND (moving_pace_seconds_per_100m IS NULL OR moving_pace_seconds_per_100m >= 0) "
        "AND (swim_pace_seconds_per_100m IS NULL OR swim_pace_seconds_per_100m >= 0) "
        "AND (timer_pace_seconds_per_100m IS NULL OR timer_pace_seconds_per_100m >= 0) "
        "AND (session_pace_seconds_per_100m IS NULL OR session_pace_seconds_per_100m >= 0)",
    )

    for name in ("moving_seconds", "swim_seconds", "rest_seconds", "stationary_seconds"):
        op.add_column("activity_lap", sa.Column(name, NUMERIC, nullable=True))
    op.add_column(
        "activity_lap",
        sa.Column("garmin_reported_speed_m_per_s", SPEED_NUMERIC, nullable=True),
    )
    _add_paces("activity_lap", elapsed_name="elapsed_pace_seconds_per_100m")
    for name in ("detected_stroke", "planned_stroke"):
        op.add_column("activity_lap", sa.Column(name, sa.String(50), nullable=True))
    op.add_column(
        "activity_lap",
        sa.Column(
            "provenance_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "activity_lap",
        sa.Column(
            "quality_warnings_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.drop_constraint("ck_activity_lap_durations", "activity_lap", type_="check")
    op.create_check_constraint(
        "ck_activity_lap_durations",
        "activity_lap",
        "start_offset_seconds >= 0 AND elapsed_seconds >= 0 AND timer_seconds >= 0 "
        "AND (moving_seconds IS NULL OR moving_seconds >= 0) "
        "AND (swim_seconds IS NULL OR swim_seconds >= 0) "
        "AND (rest_seconds IS NULL OR rest_seconds >= 0) "
        "AND (stationary_seconds IS NULL OR stationary_seconds >= 0)",
    )
    op.create_check_constraint(
        "ck_activity_lap_garmin_speed",
        "activity_lap",
        "garmin_reported_speed_m_per_s IS NULL OR garmin_reported_speed_m_per_s >= 0",
    )

    for name in (
        "elapsed_seconds",
        "timer_seconds",
        "moving_seconds",
        "swim_seconds",
        "stationary_seconds",
    ):
        op.add_column("activity_interval", sa.Column(name, NUMERIC, nullable=True))
    op.add_column(
        "activity_interval",
        sa.Column("garmin_reported_speed_m_per_s", SPEED_NUMERIC, nullable=True),
    )
    _add_paces("activity_interval", elapsed_name="elapsed_pace_seconds_per_100m")
    for name in ("detected_stroke", "planned_stroke"):
        op.add_column("activity_interval", sa.Column(name, sa.String(50), nullable=True))
    op.add_column("activity_interval", sa.Column("planned_role", sa.String(20), nullable=True))
    op.add_column(
        "activity_interval",
        sa.Column(
            "provenance_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "activity_interval",
        sa.Column(
            "quality_warnings_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.drop_constraint("ck_activity_interval_type", "activity_interval", type_="check")
    op.create_check_constraint(
        "ck_activity_interval_type",
        "activity_interval",
        "interval_type IN ('work','swim','rest','drill','unknown')",
    )
    op.create_check_constraint(
        "ck_activity_interval_planned_role",
        "activity_interval",
        "planned_role IS NULL OR planned_role IN "
        "('warmup','work','recovery','rest','cooldown','drill','other')",
    )
    op.drop_constraint("ck_activity_interval_durations", "activity_interval", type_="check")
    op.create_check_constraint(
        "ck_activity_interval_durations",
        "activity_interval",
        "start_offset_seconds >= 0 AND duration_seconds >= 0 AND rest_seconds >= 0 "
        "AND (elapsed_seconds IS NULL OR elapsed_seconds >= 0) "
        "AND (timer_seconds IS NULL OR timer_seconds >= 0) "
        "AND (moving_seconds IS NULL OR moving_seconds >= 0) "
        "AND (swim_seconds IS NULL OR swim_seconds >= 0) "
        "AND (stationary_seconds IS NULL OR stationary_seconds >= 0)",
    )
    op.create_check_constraint(
        "ck_activity_interval_garmin_speed",
        "activity_interval",
        "garmin_reported_speed_m_per_s IS NULL OR garmin_reported_speed_m_per_s >= 0",
    )

    op.add_column(
        "activity_length",
        sa.Column("length_type", sa.String(20), nullable=False, server_default="active"),
    )
    for name in (
        "elapsed_seconds",
        "timer_seconds",
        "moving_seconds",
        "swim_seconds",
        "rest_seconds",
        "stationary_seconds",
    ):
        op.add_column("activity_length", sa.Column(name, NUMERIC, nullable=True))
    op.add_column(
        "activity_length",
        sa.Column("garmin_reported_speed_m_per_s", SPEED_NUMERIC, nullable=True),
    )
    _add_paces("activity_length", elapsed_name="elapsed_pace_seconds_per_100m")
    for name in ("detected_stroke", "planned_stroke"):
        op.add_column("activity_length", sa.Column(name, sa.String(50), nullable=True))
    op.add_column(
        "activity_length",
        sa.Column(
            "provenance_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "activity_length",
        sa.Column(
            "quality_warnings_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.drop_constraint("ck_activity_length_values", "activity_length", type_="check")
    op.create_check_constraint(
        "ck_activity_length_values",
        "activity_length",
        "length_index >= 0 AND distance_m >= 0 AND duration_seconds >= 0 "
        "AND length_type IN ('active','idle','unknown') "
        "AND (length_type <> 'active' OR distance_m > 0) "
        "AND (length_type <> 'idle' OR distance_m = 0) "
        "AND (elapsed_seconds IS NULL OR elapsed_seconds >= 0) "
        "AND (timer_seconds IS NULL OR timer_seconds >= 0) "
        "AND (moving_seconds IS NULL OR moving_seconds >= 0) "
        "AND (swim_seconds IS NULL OR swim_seconds >= 0) "
        "AND (rest_seconds IS NULL OR rest_seconds >= 0) "
        "AND (stationary_seconds IS NULL OR stationary_seconds >= 0)",
    )
    op.create_check_constraint(
        "ck_activity_length_garmin_speed",
        "activity_length",
        "garmin_reported_speed_m_per_s IS NULL OR garmin_reported_speed_m_per_s >= 0",
    )

    # A normalization and its context-specific analysis are published as one
    # pair. Backfill the most recent matching legacy analysis so frozen v1 reads
    # retain their previous behavior immediately after the additive migration.
    op.add_column("activity", sa.Column("current_analysis_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_activity_current_analysis",
        "activity",
        "activity_analysis",
        ["current_analysis_id"],
        ["id"],
        ondelete="SET NULL",
        use_alter=True,
    )
    op.execute(
        """
        UPDATE activity AS activity_row
        SET current_analysis_id = (
            SELECT analysis.id
            FROM activity_analysis AS analysis
            WHERE analysis.activity_id = activity_row.id
              AND analysis.normalization_id = activity_row.current_normalization_id
            ORDER BY analysis.created_at DESC, analysis.id DESC
            LIMIT 1
        )
        WHERE activity_row.current_normalization_id IS NOT NULL
        """
    )


def downgrade() -> None:
    # The v1 schema cannot represent canonical-v2 rows. Legacy parser-v1 facts
    # remain byte-for-byte compatible, so allow their downgrade while refusing
    # any v2 row (or nullable moving fact) before mutating the schema.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM activity_normalization
                WHERE parser_version NOT LIKE '%|swim-coach:1.%'
                   OR moving_seconds IS NULL
                LIMIT 1
            ) THEN
                RAISE EXCEPTION
                    '000012 downgrade is unsafe with persisted canonical-v2 normalizations'
                    USING ERRCODE = '55000';
            END IF;
        END
        $$
        """
    )

    op.drop_constraint("fk_activity_current_analysis", "activity", type_="foreignkey")
    op.drop_column("activity", "current_analysis_id")

    op.drop_constraint("ck_activity_length_garmin_speed", "activity_length", type_="check")
    op.drop_constraint("ck_activity_length_values", "activity_length", type_="check")
    op.create_check_constraint(
        "ck_activity_length_values",
        "activity_length",
        "length_index >= 0 AND distance_m > 0 AND duration_seconds >= 0",
    )
    for name in ("quality_warnings_json", "provenance_json", "planned_stroke", "detected_stroke"):
        op.drop_column("activity_length", name)
    _drop_paces("activity_length", elapsed_name="elapsed_pace_seconds_per_100m")
    op.drop_column("activity_length", "garmin_reported_speed_m_per_s")
    for name in reversed(
        (
            "elapsed_seconds",
            "timer_seconds",
            "moving_seconds",
            "swim_seconds",
            "rest_seconds",
            "stationary_seconds",
        )
    ):
        op.drop_column("activity_length", name)
    op.drop_column("activity_length", "length_type")

    op.drop_constraint("ck_activity_interval_garmin_speed", "activity_interval", type_="check")
    op.drop_constraint("ck_activity_interval_planned_role", "activity_interval", type_="check")
    op.drop_constraint("ck_activity_interval_durations", "activity_interval", type_="check")
    op.create_check_constraint(
        "ck_activity_interval_durations",
        "activity_interval",
        "start_offset_seconds >= 0 AND duration_seconds >= 0 AND rest_seconds >= 0",
    )
    op.drop_constraint("ck_activity_interval_type", "activity_interval", type_="check")
    op.create_check_constraint(
        "ck_activity_interval_type",
        "activity_interval",
        "interval_type IN ('work','rest')",
    )
    for name in (
        "quality_warnings_json",
        "provenance_json",
        "planned_role",
        "planned_stroke",
        "detected_stroke",
    ):
        op.drop_column("activity_interval", name)
    _drop_paces("activity_interval", elapsed_name="elapsed_pace_seconds_per_100m")
    op.drop_column("activity_interval", "garmin_reported_speed_m_per_s")
    for name in reversed(
        (
            "elapsed_seconds",
            "timer_seconds",
            "moving_seconds",
            "swim_seconds",
            "stationary_seconds",
        )
    ):
        op.drop_column("activity_interval", name)

    op.drop_constraint("ck_activity_lap_garmin_speed", "activity_lap", type_="check")
    op.drop_constraint("ck_activity_lap_durations", "activity_lap", type_="check")
    op.create_check_constraint(
        "ck_activity_lap_durations",
        "activity_lap",
        "start_offset_seconds >= 0 AND elapsed_seconds >= 0 AND timer_seconds >= 0",
    )
    for name in ("quality_warnings_json", "provenance_json", "planned_stroke", "detected_stroke"):
        op.drop_column("activity_lap", name)
    _drop_paces("activity_lap", elapsed_name="elapsed_pace_seconds_per_100m")
    op.drop_column("activity_lap", "garmin_reported_speed_m_per_s")
    for name in reversed(("moving_seconds", "swim_seconds", "rest_seconds", "stationary_seconds")):
        op.drop_column("activity_lap", name)

    op.drop_constraint("ck_activity_normalization_paces", "activity_normalization", type_="check")
    op.drop_constraint(
        "ck_activity_normalization_durations", "activity_normalization", type_="check"
    )
    op.create_check_constraint(
        "ck_activity_normalization_durations",
        "activity_normalization",
        "elapsed_seconds >= 0 AND timer_seconds >= 0 AND moving_seconds >= 0",
    )
    op.drop_column("activity_normalization", "provenance_json")
    _drop_paces("activity_normalization", elapsed_name="session_pace_seconds_per_100m")
    op.drop_column("activity_normalization", "garmin_reported_speed_m_per_s")
    for name in reversed(("swim_seconds", "rest_seconds", "stationary_seconds")):
        op.drop_column("activity_normalization", name)
    op.alter_column("activity_normalization", "moving_seconds", nullable=False)
