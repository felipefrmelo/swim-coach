"""Versioned adaptive training cycles and stable feedback identity.

Revision ID: 000014
Revises: 000013
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "000014"
down_revision: str | None = "000013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    jsonb = postgresql.JSONB(astext_type=sa.Text())

    op.add_column("session_feedback", sa.Column("provider", sa.String(50), nullable=True))
    op.add_column(
        "session_feedback", sa.Column("external_activity_id", sa.String(255), nullable=True)
    )
    op.execute(
        """
        UPDATE session_feedback AS feedback
        SET provider = activity.provider,
            external_activity_id = activity.external_activity_id
        FROM activity
        WHERE feedback.activity_id = activity.id
        """
    )
    op.alter_column("session_feedback", "provider", nullable=False)
    op.alter_column("session_feedback", "external_activity_id", nullable=False)
    op.drop_constraint("session_feedback_activity_id_fkey", "session_feedback", type_="foreignkey")
    op.alter_column("session_feedback", "activity_id", existing_type=sa.Uuid(), nullable=True)
    op.create_foreign_key(
        "fk_session_feedback_activity_relinkable",
        "session_feedback",
        "activity",
        ["activity_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_unique_constraint(
        "uq_session_feedback_external_identity",
        "session_feedback",
        ["user_id", "provider", "external_activity_id"],
    )

    op.create_table(
        "training_plan",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("goal_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("duration_weeks", sa.Integer(), nullable=False),
        sa.Column("adaptation_mode", sa.String(30), nullable=False),
        sa.Column("current_revision", sa.Integer(), nullable=False),
        sa.Column("current_revision_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "status IN ('DRAFT','ACTIVE','PAUSED','COMPLETED','CANCELLED')",
            name="ck_training_plan_status",
        ),
        sa.CheckConstraint("duration_weeks BETWEEN 4 AND 16", name="ck_training_plan_duration"),
        sa.CheckConstraint("end_date >= start_date", name="ck_training_plan_dates"),
        sa.CheckConstraint(
            "current_revision >= 0 AND version >= 1", name="ck_training_plan_versions"
        ),
        sa.CheckConstraint(
            "adaptation_mode = 'MANUAL_APPROVAL'", name="ck_training_plan_adaptation_mode"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["goal_id"], ["training_goal.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_training_plan_user_status", "training_plan", ["user_id", "status"])
    op.create_index(
        "uq_training_plan_one_live_per_user",
        "training_plan",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('ACTIVE','PAUSED')"),
    )
    op.create_table(
        "training_plan_revision",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("previous_revision_id", sa.Uuid(), nullable=True),
        sa.Column("document_json", jsonb, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("reason", sa.String(1000), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=True),
        sa.Column("evidence_json", jsonb, nullable=False),
        sa.Column("diff_json", jsonb, nullable=False),
        sa.Column("proposal_id", sa.Uuid(), nullable=True),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("revision_number >= 1", name="ck_training_plan_revision_number"),
        sa.ForeignKeyConstraint(["plan_id"], ["training_plan.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["previous_revision_id"], ["training_plan_revision.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["proposal_id"], ["action_proposal.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("plan_id", "revision_number", name="uq_training_plan_revision_number"),
        sa.UniqueConstraint("plan_id", "content_hash", name="uq_training_plan_revision_hash"),
    )
    op.create_index(
        "ix_training_plan_revision_plan_created",
        "training_plan_revision",
        ["plan_id", "created_at"],
    )
    op.execute(
        """
        CREATE FUNCTION reject_training_plan_revision_update() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION 'training plan revisions are immutable' USING ERRCODE = '55000';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_training_plan_revision_immutable
        BEFORE UPDATE ON training_plan_revision
        FOR EACH ROW EXECUTE FUNCTION reject_training_plan_revision_update()
        """
    )
    op.create_foreign_key(
        "fk_training_plan_current_revision",
        "training_plan",
        "training_plan_revision",
        ["current_revision_id"],
        ["id"],
        ondelete="RESTRICT",
        use_alter=True,
    )

    op.create_table(
        "plan_session_binding",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("session_intent_id", sa.Uuid(), nullable=False),
        sa.Column("week_number", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("workout_id", sa.Uuid(), nullable=True),
        sa.Column("materialized_plan_revision", sa.Integer(), nullable=True),
        sa.Column("materialized_workout_hash", sa.String(64), nullable=True),
        sa.Column("locked_reason", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint("week_number >= 1 AND version >= 1", name="ck_plan_session_versions"),
        sa.CheckConstraint(
            "state IN ('PLANNED','MATERIALIZED','COMPLETED','SKIPPED','CANCELLED','SUPERSEDED')",
            name="ck_plan_session_state",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["plan_id"], ["training_plan.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workout_id"], ["planned_workout.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("plan_id", "session_intent_id", name="uq_plan_session_intent"),
        sa.UniqueConstraint("workout_id", name="uq_plan_session_workout"),
    )
    op.create_index("ix_plan_session_plan_week", "plan_session_binding", ["plan_id", "week_number"])

    op.create_table(
        "plan_review",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("plan_revision", sa.Integer(), nullable=False),
        sa.Column("week_number", sa.Integer(), nullable=False),
        sa.Column("evidence_snapshot_json", jsonb, nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("confidence_cap", sa.String(10), nullable=False),
        sa.Column("eligible", sa.Boolean(), nullable=False),
        sa.Column("eligibility_reason", sa.String(500), nullable=False),
        sa.Column("decision", sa.String(20), nullable=True),
        sa.Column("rationale", sa.String(2000), nullable=True),
        sa.Column("recommendation_json", jsonb, nullable=False),
        sa.Column("proposal_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("plan_revision >= 1 AND week_number >= 1", name="ck_plan_review_target"),
        sa.CheckConstraint(
            "confidence_cap IN ('LOW','MEDIUM','HIGH')", name="ck_plan_review_confidence"
        ),
        sa.CheckConstraint(
            "decision IS NULL OR decision IN "
            "('PROGRESS','HOLD','REGRESS','RECOVERY','RETEST','RESCHEDULE','PAUSE')",
            name="ck_plan_review_decision",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["plan_id"], ["training_plan.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["proposal_id"], ["action_proposal.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "plan_id",
            "plan_revision",
            "week_number",
            "evidence_hash",
            name="uq_plan_review_evidence",
        ),
    )
    op.create_index(
        "ix_plan_review_plan_week", "plan_review", ["plan_id", "week_number", "created_at"]
    )

    op.create_table(
        "plan_note",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("scope_type", sa.String(20), nullable=False),
        sa.Column("scope_ref", sa.String(255), nullable=False),
        sa.Column("category", sa.String(30), nullable=False),
        sa.Column("author_type", sa.String(30), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("importance", sa.String(10), nullable=False),
        sa.Column("affects_adaptation", sa.Boolean(), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=True),
        sa.Column("valid_until", sa.Date(), nullable=True),
        sa.Column("evidence_activity_refs_json", jsonb, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "scope_type IN ('PLAN','WEEK','SESSION','ACTIVITY')", name="ck_plan_note_scope"
        ),
        sa.CheckConstraint(
            "category IN ('PERFORMANCE','TECHNIQUE','PAIN','RECOVERY','SCHEDULE',"
            "'DECISION','DATA_QUALITY')",
            name="ck_plan_note_category",
        ),
        sa.CheckConstraint("importance IN ('LOW','MEDIUM','HIGH')", name="ck_plan_note_importance"),
        sa.CheckConstraint(
            "author_type IN ('ATHLETE','COACH','SYSTEM')", name="ck_plan_note_author"
        ),
        sa.CheckConstraint(
            "valid_until IS NULL OR valid_from IS NULL OR valid_until >= valid_from",
            name="ck_plan_note_validity",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["plan_id"], ["training_plan.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_plan_note_plan_scope", "plan_note", ["plan_id", "scope_type", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_plan_note_plan_scope", table_name="plan_note")
    op.drop_table("plan_note")
    op.drop_index("ix_plan_review_plan_week", table_name="plan_review")
    op.drop_table("plan_review")
    op.drop_index("ix_plan_session_plan_week", table_name="plan_session_binding")
    op.drop_table("plan_session_binding")
    op.drop_constraint("fk_training_plan_current_revision", "training_plan", type_="foreignkey")
    op.execute("DROP TRIGGER trg_training_plan_revision_immutable ON training_plan_revision")
    op.execute("DROP FUNCTION reject_training_plan_revision_update()")
    op.drop_index("ix_training_plan_revision_plan_created", table_name="training_plan_revision")
    op.drop_table("training_plan_revision")
    op.drop_index("uq_training_plan_one_live_per_user", table_name="training_plan")
    op.drop_index("ix_training_plan_user_status", table_name="training_plan")
    op.drop_table("training_plan")

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM session_feedback WHERE activity_id IS NULL LIMIT 1) THEN
                RAISE EXCEPTION
                    '000014 downgrade is unsafe with detached stable feedback'
                    USING ERRCODE = '55000';
            END IF;
        END
        $$
        """
    )
    op.drop_constraint("uq_session_feedback_external_identity", "session_feedback", type_="unique")
    op.drop_constraint(
        "fk_session_feedback_activity_relinkable", "session_feedback", type_="foreignkey"
    )
    op.alter_column("session_feedback", "activity_id", existing_type=sa.Uuid(), nullable=False)
    op.create_foreign_key(
        "session_feedback_activity_id_fkey",
        "session_feedback",
        "activity",
        ["activity_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_column("session_feedback", "external_activity_id")
    op.drop_column("session_feedback", "provider")
