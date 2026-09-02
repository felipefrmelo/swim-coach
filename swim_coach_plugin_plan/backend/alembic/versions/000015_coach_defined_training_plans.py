"""Coach-defined training plans and explicit revision intent.

Revision ID: 000015
Revises: 000014
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "000015"
down_revision: str | None = "000014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("uq_training_plan_revision_hash", "training_plan_revision", type_="unique")
    op.create_index(
        "ix_training_plan_revision_content_hash",
        "training_plan_revision",
        ["plan_id", "content_hash"],
    )
    op.add_column(
        "training_plan",
        sa.Column(
            "prescription_source",
            sa.String(30),
            nullable=False,
            server_default="LEGACY_RULESET",
        ),
    )
    op.alter_column("training_plan", "prescription_source", server_default=None)
    op.create_check_constraint(
        "ck_training_plan_prescription_source",
        "training_plan",
        "prescription_source IN ('COACH_DEFINED','LEGACY_RULESET')",
    )

    op.add_column(
        "training_plan_revision",
        sa.Column(
            "revision_kind",
            sa.String(30),
            nullable=False,
            server_default="LEGACY",
        ),
    )
    op.alter_column("training_plan_revision", "revision_kind", server_default=None)
    op.add_column(
        "training_plan_revision",
        sa.Column("decision", sa.String(20), nullable=True),
    )
    op.create_check_constraint(
        "ck_training_plan_revision_kind",
        "training_plan_revision",
        "revision_kind IN ('CREATION','ADAPTATION','MATERIALIZATION','LEGACY')",
    )
    op.create_check_constraint(
        "ck_training_plan_revision_decision",
        "training_plan_revision",
        "decision IS NULL OR decision IN "
        "('PROGRESS','HOLD','REGRESS','RECOVERY','RETEST','RESCHEDULE','PAUSE')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_training_plan_revision_decision", "training_plan_revision", type_="check"
    )
    op.drop_constraint("ck_training_plan_revision_kind", "training_plan_revision", type_="check")
    op.drop_column("training_plan_revision", "decision")
    op.drop_column("training_plan_revision", "revision_kind")
    op.drop_constraint("ck_training_plan_prescription_source", "training_plan", type_="check")
    op.drop_column("training_plan", "prescription_source")
    op.drop_index("ix_training_plan_revision_content_hash", table_name="training_plan_revision")
    op.create_unique_constraint(
        "uq_training_plan_revision_hash",
        "training_plan_revision",
        ["plan_id", "content_hash"],
    )
