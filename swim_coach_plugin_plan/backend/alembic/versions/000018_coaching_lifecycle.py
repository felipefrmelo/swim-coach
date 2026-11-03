"""Link successor cycles and preserve goal snapshots without rewriting history."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "000018"
down_revision = "000017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("training_plan", sa.Column("predecessor_plan_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_plan_predecessor",
        "training_plan",
        "training_plan",
        ["predecessor_plan_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.add_column(
        "training_plan",
        sa.Column("goal_snapshot", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.drop_constraint("ck_training_plan_status", "training_plan", type_="check")
    op.create_check_constraint(
        "ck_training_plan_status",
        "training_plan",
        "status IN ('DRAFT','ACTIVE','PAUSED','COMPLETED','CANCELLED','SUPERSEDED')",
    )
    op.drop_constraint("ck_training_plan_revision_kind", "training_plan_revision", type_="check")
    op.create_check_constraint(
        "ck_training_plan_revision_kind",
        "training_plan_revision",
        "revision_kind IN ('CREATION','ADAPTATION','MATERIALIZATION','LEGACY','RESCHEDULE')",
    )


def downgrade() -> None:
    # Older images require schema 000017 and cannot read new persisted enum/JSON fields.
    count = op.get_bind().scalar(
        sa.text(
            "SELECT count(*) FROM training_plan WHERE "
            "predecessor_plan_id IS NOT NULL OR goal_snapshot <> '{}'::jsonb OR status='SUPERSEDED'"
        )
    )
    revisions = op.get_bind().scalar(
        sa.text("SELECT count(*) FROM training_plan_revision WHERE revision_kind='RESCHEDULE'")
    )
    check_ins = op.get_bind().scalar(
        sa.text(
            "SELECT count(*) FROM session_feedback "
            "WHERE check_in_json ->> 'confirmed_distance_m' IS NOT NULL"
        )
    )
    workout_metadata = op.get_bind().scalar(
        sa.text(
            "SELECT count(*) FROM workout_revision "
            "WHERE validation_json -> 'totals' ? 'duration_complete'"
        )
    )
    if count or revisions or check_ins or workout_metadata:
        raise RuntimeError(
            "Lifecycle data exists; retain schema and restore a verified backup if required."
        )
    op.drop_constraint("ck_training_plan_revision_kind", "training_plan_revision", type_="check")
    op.create_check_constraint(
        "ck_training_plan_revision_kind",
        "training_plan_revision",
        "revision_kind IN ('CREATION','ADAPTATION','MATERIALIZATION','LEGACY')",
    )
    op.drop_constraint("ck_training_plan_status", "training_plan", type_="check")
    op.create_check_constraint(
        "ck_training_plan_status",
        "training_plan",
        "status IN ('DRAFT','ACTIVE','PAUSED','COMPLETED','CANCELLED')",
    )
    op.drop_column("training_plan", "goal_snapshot")
    op.drop_constraint("fk_plan_predecessor", "training_plan", type_="foreignkey")
    op.drop_column("training_plan", "predecessor_plan_id")
