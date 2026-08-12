"""P10 versioned deterministic weekly planning.

Revision ID: 000008
Revises: 000007
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "000008"
down_revision: str | None = "000007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    jsonb = postgresql.JSONB(astext_type=sa.Text())
    op.alter_column("action_proposal", "target_revision_id", nullable=True)
    op.create_table(
        "training_rule_set",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("version", sa.String(40), nullable=False),
        sa.Column("rules_json", jsonb, nullable=False),
        sa.Column("schema_version", sa.String(20), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_until", sa.Date(), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "effective_until IS NULL OR effective_until >= effective_from",
            name="ck_training_rule_set_effective_range",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("content_hash", name="uq_training_rule_set_hash"),
        sa.UniqueConstraint("name", "version", name="uq_training_rule_set_name_version"),
    )
    op.create_index(
        "ix_training_rule_set_effective",
        "training_rule_set",
        ["effective_from", "effective_until"],
    )
    op.create_table(
        "planning_run",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("goal_id", sa.Uuid(), nullable=False),
        sa.Column("rule_set_id", sa.Uuid(), nullable=False),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("input_snapshot_json", jsonb, nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("output_plan_json", jsonb, nullable=False),
        sa.Column("output_proposal_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("warnings_json", jsonb, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('COMPLETED','FAILED')", name="ck_planning_run_status"),
        sa.ForeignKeyConstraint(["goal_id"], ["training_goal.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["rule_set_id"], ["training_rule_set.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "rule_set_id", "input_hash", name="uq_planning_run_reproducible_input"
        ),
    )
    op.create_index(
        "ix_planning_run_user_week", "planning_run", ["user_id", "week_start", "created_at"]
    )
    op.create_table(
        "training_decision",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("planning_run_id", sa.Uuid(), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("decision_type", sa.String(100), nullable=False),
        sa.Column("rule_id", sa.String(100), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("evidence_refs_json", jsonb, nullable=False),
        sa.Column("before_json", jsonb, nullable=False),
        sa.Column("after_json", jsonb, nullable=False),
        sa.Column("rationale", sa.String(1000), nullable=False),
        sa.Column("actor_type", sa.String(30), nullable=False),
        sa.Column("actor_id", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("order_index >= 1", name="ck_training_decision_order"),
        sa.ForeignKeyConstraint(["planning_run_id"], ["planning_run.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "planning_run_id", "order_index", name="uq_training_decision_run_order"
        ),
    )
    op.create_index(
        "ix_training_decision_user_date", "training_decision", ["user_id", "effective_date"]
    )
    op.create_foreign_key(
        "fk_planning_run_output_proposal",
        "planning_run",
        "action_proposal",
        ["output_proposal_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_planning_run_output_proposal", "planning_run", type_="foreignkey")
    op.drop_index("ix_training_decision_user_date", table_name="training_decision")
    op.drop_table("training_decision")
    op.drop_index("ix_planning_run_user_week", table_name="planning_run")
    op.drop_table("planning_run")
    op.drop_index("ix_training_rule_set_effective", table_name="training_rule_set")
    op.drop_table("training_rule_set")
    op.execute("DELETE FROM action_proposal WHERE target_revision_id IS NULL")
    op.alter_column("action_proposal", "target_revision_id", nullable=False)
