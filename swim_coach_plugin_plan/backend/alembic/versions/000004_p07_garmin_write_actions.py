"""p07 approved Garmin write actions

Revision ID: 000004
Revises: 000003
Create Date: 2026-08-11 22:25:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "000004"
down_revision: str | None = "000003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    jsonb = postgresql.JSONB(astext_type=sa.Text())
    op.drop_constraint("ck_planned_workout_status", "planned_workout", type_="check")
    op.create_check_constraint(
        "ck_planned_workout_status",
        "planned_workout",
        "status IN ('draft','approved','scheduled','published','completed','cancelled','archived')",
    )
    op.create_table(
        "action_proposal",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("action_type", sa.String(100), nullable=False),
        sa.Column("target_type", sa.String(100), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("target_revision_id", sa.Uuid(), nullable=False),
        sa.Column("payload_json", jsonb, nullable=False),
        sa.Column("impact_json", jsonb, nullable=False),
        sa.Column("action_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "status IN ('DRAFT','READY_FOR_REVIEW','APPROVED','REJECTED','EXPIRED',"
            "'QUEUED','EXECUTING','SUCCEEDED','FAILED','NEEDS_RECONCILIATION','CANCELLED')",
            name="ck_action_proposal_status",
        ),
        sa.CheckConstraint("expires_at > created_at", name="ck_action_proposal_expiry"),
        sa.CheckConstraint("version >= 1", name="ck_action_proposal_version"),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["target_revision_id"], ["workout_revision.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "action_hash", name="uq_action_proposal_user_hash"),
    )
    op.create_index(
        "ix_action_proposal_user_status", "action_proposal", ["user_id", "status", "created_at"]
    )
    op.create_index("ix_action_proposal_target", "action_proposal", ["target_type", "target_id"])
    op.create_table(
        "action_approval",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("proposal_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("action_hash", sa.String(64), nullable=False),
        sa.Column("decision", sa.String(10), nullable=False),
        sa.Column("explicit_verb", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("decision IN ('APPROVE','REJECT')", name="ck_action_approval_decision"),
        sa.ForeignKeyConstraint(["proposal_id"], ["action_proposal.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("proposal_id", name="uq_action_approval_proposal"),
    )
    op.create_index("ix_action_approval_user_created", "action_approval", ["user_id", "created_at"])
    op.create_table(
        "action_execution",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("proposal_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("result_json", jsonb, nullable=True),
        sa.Column("error_json_redacted", jsonb, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "status IN ('QUEUED','EXECUTING','SUCCEEDED','FAILED',"
            "'NEEDS_RECONCILIATION','CANCELLED')",
            name="ck_action_execution_status",
        ),
        sa.CheckConstraint("version >= 1", name="ck_action_execution_version"),
        sa.ForeignKeyConstraint(["proposal_id"], ["action_proposal.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("proposal_id", name="uq_action_execution_proposal"),
        sa.UniqueConstraint("idempotency_key", name="uq_action_execution_idempotency"),
    )
    op.create_index("ix_action_execution_user_status", "action_execution", ["user_id", "status"])
    op.create_table(
        "external_workout_binding",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workout_id", sa.Uuid(), nullable=False),
        sa.Column("revision_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("compiled_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("external_workout_id", sa.String(255), nullable=True),
        sa.Column("external_schedule_id", sa.String(255), nullable=True),
        sa.Column("scheduled_date", sa.Date(), nullable=True),
        sa.Column("last_error_json_redacted", jsonb, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "status IN ('NOT_CREATED','CREATING','CREATED','SCHEDULING','SCHEDULED',"
            "'FAILED','NEEDS_RECONCILIATION')",
            name="ck_external_workout_binding_status",
        ),
        sa.CheckConstraint("version >= 1", name="ck_external_workout_binding_version"),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workout_id"], ["planned_workout.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["revision_id"], ["workout_revision.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "provider",
            "workout_id",
            "revision_id",
            "compiled_hash",
            name="uq_external_workout_binding_revision_hash",
        ),
        sa.UniqueConstraint(
            "user_id",
            "provider",
            "external_workout_id",
            name="uq_external_workout_binding_external",
        ),
    )
    op.create_index(
        "ix_external_workout_binding_user_status",
        "external_workout_binding",
        ["user_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_external_workout_binding_user_status", table_name="external_workout_binding")
    op.drop_table("external_workout_binding")
    op.drop_index("ix_action_execution_user_status", table_name="action_execution")
    op.drop_table("action_execution")
    op.drop_index("ix_action_approval_user_created", table_name="action_approval")
    op.drop_table("action_approval")
    op.drop_index("ix_action_proposal_target", table_name="action_proposal")
    op.drop_index("ix_action_proposal_user_status", table_name="action_proposal")
    op.drop_table("action_proposal")
    op.drop_constraint("ck_planned_workout_status", "planned_workout", type_="check")
    op.create_check_constraint(
        "ck_planned_workout_status",
        "planned_workout",
        "status IN ('draft','approved','scheduled','cancelled','archived')",
    )
