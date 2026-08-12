"""P03 immutable FIT artifacts, normalization, analytics, matching and feedback.

Revision ID: 000005
Revises: 000004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "000005"
down_revision: str | None = "000004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "file_artifact",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "activity_id",
            sa.Uuid(),
            sa.ForeignKey("activity.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("artifact_type", sa.String(30), nullable=False),
        sa.Column("storage_key", sa.String(1024), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("source_external_id_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("size_bytes > 0", name="ck_file_artifact_size"),
        sa.UniqueConstraint(
            "activity_id",
            "checksum",
            "artifact_type",
            name="uq_file_artifact_activity_checksum_type",
        ),
        sa.UniqueConstraint("storage_key", name="uq_file_artifact_storage_key"),
    )
    op.create_index("ix_file_artifact_activity", "file_artifact", ["activity_id", "created_at"])

    op.create_table(
        "activity_normalization",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "activity_id",
            sa.Uuid(),
            sa.ForeignKey("activity.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "artifact_id",
            sa.Uuid(),
            sa.ForeignKey("file_artifact.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("parser_version", sa.String(160), nullable=False),
        sa.Column("profile_version", sa.String(80), nullable=False),
        sa.Column("input_checksum", sa.String(64), nullable=False),
        sa.Column("pool_length_m", sa.Integer(), nullable=False),
        sa.Column("distance_m", sa.Integer(), nullable=False),
        sa.Column("elapsed_seconds", sa.Numeric(14, 3), nullable=False),
        sa.Column("timer_seconds", sa.Numeric(14, 3), nullable=False),
        sa.Column("moving_seconds", sa.Numeric(14, 3), nullable=False),
        sa.Column("active_length_count", sa.Integer(), nullable=False),
        sa.Column("completeness", sa.Numeric(5, 4), nullable=False),
        sa.Column("quality", sa.String(20), nullable=False),
        sa.Column("warnings_json", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "pool_length_m > 0 AND distance_m >= 0 AND active_length_count >= 0",
            name="ck_activity_normalization_totals",
        ),
        sa.CheckConstraint(
            "elapsed_seconds >= 0 AND timer_seconds >= 0 AND moving_seconds >= 0",
            name="ck_activity_normalization_durations",
        ),
        sa.CheckConstraint(
            "completeness BETWEEN 0 AND 1", name="ck_activity_normalization_completeness"
        ),
        sa.CheckConstraint(
            "quality IN ('complete','partial','poor')", name="ck_activity_normalization_quality"
        ),
        sa.UniqueConstraint(
            "activity_id",
            "parser_version",
            "input_checksum",
            name="uq_activity_normalization_input_version",
        ),
    )
    op.create_index(
        "ix_activity_normalization_activity_created",
        "activity_normalization",
        ["activity_id", "created_at"],
    )

    op.add_column("activity", sa.Column("current_normalization_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_activity_current_normalization",
        "activity",
        "activity_normalization",
        ["current_normalization_id"],
        ["id"],
        ondelete="SET NULL",
        use_alter=True,
    )

    op.create_table(
        "activity_lap",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "normalization_id",
            sa.Uuid(),
            sa.ForeignKey("activity_normalization.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("lap_index", sa.Integer(), nullable=False),
        sa.Column("start_offset_seconds", sa.Numeric(14, 3), nullable=False),
        sa.Column("elapsed_seconds", sa.Numeric(14, 3), nullable=False),
        sa.Column("timer_seconds", sa.Numeric(14, 3), nullable=False),
        sa.Column("distance_m", sa.Integer(), nullable=False),
        sa.Column("avg_hr_bpm", sa.Integer(), nullable=True),
        sa.Column("max_hr_bpm", sa.Integer(), nullable=True),
        sa.Column("stroke_type", sa.String(50), nullable=True),
        sa.CheckConstraint(
            "lap_index >= 0 AND distance_m >= 0", name="ck_activity_lap_index_distance"
        ),
        sa.CheckConstraint(
            "start_offset_seconds >= 0 AND elapsed_seconds >= 0 AND timer_seconds >= 0",
            name="ck_activity_lap_durations",
        ),
        sa.UniqueConstraint(
            "normalization_id", "lap_index", name="uq_activity_lap_normalization_index"
        ),
    )
    op.create_table(
        "activity_interval",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "normalization_id",
            sa.Uuid(),
            sa.ForeignKey("activity_normalization.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("interval_index", sa.Integer(), nullable=False),
        sa.Column("interval_type", sa.String(20), nullable=False),
        sa.Column("start_offset_seconds", sa.Numeric(14, 3), nullable=False),
        sa.Column("duration_seconds", sa.Numeric(14, 3), nullable=False),
        sa.Column("rest_seconds", sa.Numeric(14, 3), nullable=False),
        sa.Column("distance_m", sa.Integer(), nullable=False),
        sa.Column("pace_seconds_per_100m", sa.Numeric(14, 3), nullable=True),
        sa.Column("avg_hr_bpm", sa.Integer(), nullable=True),
        sa.Column("max_hr_bpm", sa.Integer(), nullable=True),
        sa.Column("stroke_type", sa.String(50), nullable=True),
        sa.Column("stroke_count", sa.Integer(), nullable=True),
        sa.Column("stroke_rate", sa.Numeric(14, 3), nullable=True),
        sa.Column("swolf", sa.Numeric(14, 3), nullable=True),
        sa.Column("source_json", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.CheckConstraint("interval_type IN ('work','rest')", name="ck_activity_interval_type"),
        sa.CheckConstraint(
            "interval_index >= 0 AND distance_m >= 0", name="ck_activity_interval_index_distance"
        ),
        sa.CheckConstraint(
            "start_offset_seconds >= 0 AND duration_seconds >= 0 AND rest_seconds >= 0",
            name="ck_activity_interval_durations",
        ),
        sa.UniqueConstraint(
            "normalization_id", "interval_index", name="uq_activity_interval_normalization_index"
        ),
    )
    op.create_table(
        "activity_length",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "normalization_id",
            sa.Uuid(),
            sa.ForeignKey("activity_normalization.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "interval_id",
            sa.Uuid(),
            sa.ForeignKey("activity_interval.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("length_index", sa.Integer(), nullable=False),
        sa.Column("distance_m", sa.Integer(), nullable=False),
        sa.Column("duration_seconds", sa.Numeric(14, 3), nullable=False),
        sa.Column("stroke_type", sa.String(50), nullable=True),
        sa.Column("stroke_count", sa.Integer(), nullable=True),
        sa.Column("stroke_rate", sa.Numeric(14, 3), nullable=True),
        sa.Column("swolf", sa.Numeric(14, 3), nullable=True),
        sa.Column("avg_hr_bpm", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "length_index >= 0 AND distance_m > 0 AND duration_seconds >= 0",
            name="ck_activity_length_values",
        ),
        sa.UniqueConstraint(
            "normalization_id", "length_index", name="uq_activity_length_normalization_index"
        ),
    )

    op.create_table(
        "activity_analysis",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "activity_id",
            sa.Uuid(),
            sa.ForeignKey("activity.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "normalization_id",
            sa.Uuid(),
            sa.ForeignKey("activity_normalization.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "planned_workout_id",
            sa.Uuid(),
            sa.ForeignKey("planned_workout.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("analysis_version", sa.String(80), nullable=False),
        sa.Column("parser_version", sa.String(160), nullable=False),
        sa.Column("input_checksum", sa.String(64), nullable=False),
        sa.Column("pool_length_m", sa.Integer(), nullable=False),
        sa.Column("metrics_json", postgresql.JSONB(), nullable=False),
        sa.Column("flags_json", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("quality", sa.String(20), nullable=False),
        sa.Column("summary_json", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("pool_length_m > 0", name="ck_activity_analysis_pool"),
        sa.CheckConstraint(
            "quality IN ('complete','partial','poor')", name="ck_activity_analysis_quality"
        ),
    )
    op.create_index(
        "uq_activity_analysis_version_target",
        "activity_analysis",
        [
            "normalization_id",
            "analysis_version",
            sa.text("coalesce(planned_workout_id, '00000000-0000-0000-0000-000000000000'::uuid)"),
        ],
        unique=True,
    )
    op.create_index(
        "ix_activity_analysis_activity_created", "activity_analysis", ["activity_id", "created_at"]
    )

    op.create_table(
        "workout_execution_match",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "activity_id",
            sa.Uuid(),
            sa.ForeignKey("activity.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "planned_workout_id",
            sa.Uuid(),
            sa.ForeignKey("planned_workout.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("method", sa.String(20), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False),
        sa.Column("score_details_json", postgresql.JSONB(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_by", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "method IN ('automatic','suggested','manual')", name="ck_workout_execution_match_method"
        ),
        sa.CheckConstraint(
            "confidence BETWEEN 0 AND 1", name="ck_workout_execution_match_confidence"
        ),
        sa.UniqueConstraint("activity_id", name="uq_workout_execution_match_activity"),
        sa.UniqueConstraint("planned_workout_id", name="uq_workout_execution_match_workout"),
    )

    op.create_table(
        "session_feedback",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "activity_id",
            sa.Uuid(),
            sa.ForeignKey("activity.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("rpe", sa.Integer(), nullable=False),
        sa.Column("technique_rating", sa.Integer(), nullable=True),
        sa.Column("fatigue_rating", sa.Integer(), nullable=True),
        sa.Column("enjoyment_rating", sa.Integer(), nullable=True),
        sa.Column("pain_present", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("pain_location", sa.String(120), nullable=True),
        sa.Column("pain_intensity", sa.Integer(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.CheckConstraint("rpe BETWEEN 1 AND 10", name="ck_session_feedback_rpe"),
        sa.CheckConstraint(
            "technique_rating IS NULL OR technique_rating BETWEEN 1 AND 5",
            name="ck_session_feedback_technique",
        ),
        sa.CheckConstraint(
            "fatigue_rating IS NULL OR fatigue_rating BETWEEN 1 AND 5",
            name="ck_session_feedback_fatigue",
        ),
        sa.CheckConstraint(
            "enjoyment_rating IS NULL OR enjoyment_rating BETWEEN 1 AND 5",
            name="ck_session_feedback_enjoyment",
        ),
        sa.CheckConstraint(
            "(pain_present AND pain_location IS NOT NULL "
            "AND pain_intensity BETWEEN 1 AND 10) OR "
            "(NOT pain_present AND pain_location IS NULL AND pain_intensity IS NULL)",
            name="ck_session_feedback_pain",
        ),
        sa.CheckConstraint("version >= 1", name="ck_session_feedback_version"),
        sa.UniqueConstraint("activity_id", name="uq_session_feedback_activity"),
    )


def downgrade() -> None:
    op.drop_table("session_feedback")
    op.drop_table("workout_execution_match")
    op.drop_index("ix_activity_analysis_activity_created", table_name="activity_analysis")
    op.drop_index("uq_activity_analysis_version_target", table_name="activity_analysis")
    op.drop_table("activity_analysis")
    op.drop_table("activity_length")
    op.drop_table("activity_interval")
    op.drop_table("activity_lap")
    op.drop_constraint("fk_activity_current_normalization", "activity", type_="foreignkey")
    op.drop_column("activity", "current_normalization_id")
    op.drop_index("ix_activity_normalization_activity_created", table_name="activity_normalization")
    op.drop_table("activity_normalization")
    op.drop_index("ix_file_artifact_activity", table_name="file_artifact")
    op.drop_table("file_artifact")
