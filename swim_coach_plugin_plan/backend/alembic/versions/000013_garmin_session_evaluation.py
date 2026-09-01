"""Garmin FIT session evaluation and optional local overrides.

Revision ID: 000013
Revises: 000012
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "000013"
down_revision: str | None = "000012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "activity_normalization",
        sa.Column("perceived_effort_rpe", sa.Numeric(4, 1), nullable=True),
    )
    op.add_column(
        "activity_normalization",
        sa.Column("feeling_score", sa.Integer(), nullable=True),
    )
    op.create_check_constraint(
        "ck_activity_normalization_rpe",
        "activity_normalization",
        "perceived_effort_rpe IS NULL OR perceived_effort_rpe BETWEEN 0 AND 10",
    )
    op.create_check_constraint(
        "ck_activity_normalization_feeling",
        "activity_normalization",
        "feeling_score IS NULL OR feeling_score BETWEEN 0 AND 100",
    )

    op.add_column(
        "session_feedback",
        sa.Column("feeling_score", sa.Integer(), nullable=True),
    )
    op.create_check_constraint(
        "ck_session_feedback_feeling_score",
        "session_feedback",
        "feeling_score IS NULL OR feeling_score BETWEEN 0 AND 100",
    )
    op.drop_constraint("ck_session_feedback_rpe", "session_feedback", type_="check")
    op.alter_column("session_feedback", "rpe", existing_type=sa.Integer(), nullable=True)
    op.create_check_constraint(
        "ck_session_feedback_rpe",
        "session_feedback",
        "rpe IS NULL OR rpe BETWEEN 1 AND 10",
    )


def downgrade() -> None:
    # The previous schema cannot represent Garmin-only feedback (nullable local
    # RPE), canonical Garmin evaluation facts or a local feeling override. Fail
    # before changing the schema instead of silently deleting those values.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM activity_normalization
                WHERE perceived_effort_rpe IS NOT NULL OR feeling_score IS NOT NULL
                LIMIT 1
            ) OR EXISTS (
                SELECT 1
                FROM session_feedback
                WHERE rpe IS NULL OR feeling_score IS NOT NULL
                LIMIT 1
            ) THEN
                RAISE EXCEPTION
                    '000013 downgrade is unsafe with persisted session evaluation facts'
                    USING ERRCODE = '55000';
            END IF;
        END
        $$
        """
    )

    op.drop_constraint("ck_session_feedback_rpe", "session_feedback", type_="check")
    op.alter_column("session_feedback", "rpe", existing_type=sa.Integer(), nullable=False)
    op.create_check_constraint(
        "ck_session_feedback_rpe",
        "session_feedback",
        "rpe BETWEEN 1 AND 10",
    )
    op.drop_constraint("ck_session_feedback_feeling_score", "session_feedback", type_="check")
    op.drop_column("session_feedback", "feeling_score")

    op.drop_constraint("ck_activity_normalization_feeling", "activity_normalization", type_="check")
    op.drop_constraint("ck_activity_normalization_rpe", "activity_normalization", type_="check")
    op.drop_column("activity_normalization", "feeling_score")
    op.drop_column("activity_normalization", "perceived_effort_rpe")
