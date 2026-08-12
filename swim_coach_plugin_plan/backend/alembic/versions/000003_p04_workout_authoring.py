"""p04 canonical workouts and local calendar

Revision ID: 000003
Revises: 000002
Create Date: 2026-08-11 22:10:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "000003"
down_revision: str | None = "000002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    jsonb = postgresql.JSONB(astext_type=sa.Text())
    op.create_table(
        "workout_template",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("objective", sa.String(500), nullable=False),
        sa.Column("tags_json", jsonb, nullable=False),
        sa.Column("definition_json", jsonb, nullable=False),
        sa.Column("schema_version", sa.String(20), nullable=False),
        sa.Column("is_system", sa.Boolean(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_workout_template_owner_active", "workout_template", ["owner_user_id", "active"]
    )
    op.create_table(
        "planned_workout",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("sport", sa.String(30), nullable=False),
        sa.Column("purpose", sa.String(30), nullable=False),
        sa.Column("pool_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("current_revision_id", sa.Uuid(), nullable=True),
        sa.Column("approved_revision_id", sa.Uuid(), nullable=True),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint("sport = 'POOL_SWIMMING'", name="ck_planned_workout_sport"),
        sa.CheckConstraint(
            "status IN ('draft','approved','scheduled','cancelled','archived')",
            name="ck_planned_workout_status",
        ),
        sa.CheckConstraint("version >= 1", name="ck_planned_workout_version"),
        sa.ForeignKeyConstraint(["pool_id"], ["pool.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_planned_workout_user_status", "planned_workout", ["user_id", "status"])
    op.create_table(
        "workout_revision",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workout_id", sa.Uuid(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("definition_json", jsonb, nullable=False),
        sa.Column("total_distance_m", sa.Integer(), nullable=False),
        sa.Column("estimated_active_seconds", sa.Numeric(14, 3), nullable=False),
        sa.Column("estimated_rest_seconds", sa.Numeric(14, 3), nullable=False),
        sa.Column("estimated_total_seconds", sa.Numeric(14, 3), nullable=False),
        sa.Column("distance_steps", sa.Integer(), nullable=False),
        sa.Column("executable_steps", sa.Integer(), nullable=False),
        sa.Column("lengths", sa.Integer(), nullable=False),
        sa.Column("validation_json", jsonb, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("change_reason", sa.String(500), nullable=True),
        sa.Column("created_by_type", sa.String(30), nullable=False),
        sa.Column("created_by_id", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("revision_number >= 1", name="ck_workout_revision_number"),
        sa.CheckConstraint("total_distance_m >= 0", name="ck_workout_revision_distance"),
        sa.ForeignKeyConstraint(["workout_id"], ["planned_workout.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workout_id", "revision_number", name="uq_workout_revision_number"),
    )
    op.create_index(
        "ix_workout_revision_workout_created", "workout_revision", ["workout_id", "created_at"]
    )
    op.execute(
        """
        CREATE FUNCTION reject_workout_revision_update() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION 'workout revisions are immutable' USING ERRCODE = '55000';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_workout_revision_immutable
        BEFORE UPDATE ON workout_revision
        FOR EACH ROW EXECUTE FUNCTION reject_workout_revision_update()
        """
    )
    op.create_foreign_key(
        "fk_planned_workout_current_revision",
        "planned_workout",
        "workout_revision",
        ["current_revision_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_planned_workout_approved_revision",
        "planned_workout",
        "workout_revision",
        ["approved_revision_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_table(
        "workout_schedule",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workout_id", sa.Uuid(), nullable=False),
        sa.Column("scheduled_date", sa.Date(), nullable=False),
        sa.Column("scheduled_start_time", sa.Time(), nullable=True),
        sa.Column("timezone", sa.String(100), nullable=False),
        sa.Column("pool_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["pool_id"], ["pool.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["workout_id"], ["planned_workout.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workout_id", name="uq_workout_schedule_workout"),
    )
    op.create_index("ix_workout_schedule_date", "workout_schedule", ["scheduled_date"])


def downgrade() -> None:
    op.drop_index("ix_workout_schedule_date", table_name="workout_schedule")
    op.drop_table("workout_schedule")
    op.drop_constraint(
        "fk_planned_workout_approved_revision", "planned_workout", type_="foreignkey"
    )
    op.drop_constraint("fk_planned_workout_current_revision", "planned_workout", type_="foreignkey")
    op.execute("DROP TRIGGER trg_workout_revision_immutable ON workout_revision")
    op.execute("DROP FUNCTION reject_workout_revision_update()")
    op.drop_index("ix_workout_revision_workout_created", table_name="workout_revision")
    op.drop_table("workout_revision")
    op.drop_index("ix_planned_workout_user_status", table_name="planned_workout")
    op.drop_table("planned_workout")
    op.drop_index("ix_workout_template_owner_active", table_name="workout_template")
    op.drop_table("workout_template")
