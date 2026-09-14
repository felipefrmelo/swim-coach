"""Structured athlete check-in, without changing Garmin facts.

Revision ID: 000016
Revises: 000015
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "000016"
down_revision = "000015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("session_feedback", sa.Column("check_in", JSONB(), nullable=True))


def downgrade() -> None:
    # Refuse silent loss of athlete reports. Empty installations can roll back.
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM session_feedback WHERE check_in IS NOT NULL) THEN
                RAISE EXCEPTION '000016 downgrade would discard athlete check-ins'
                    USING ERRCODE = '55000';
            END IF;
        END $$
    """)
    op.drop_column("session_feedback", "check_in")
