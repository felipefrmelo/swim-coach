"""Preserve canonical heart-rate facts and source zone distribution.

Revision ID: 000017
Revises: 000016
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "000017"
down_revision = "000016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "activity_normalization",
        sa.Column(
            "heart_rate_json", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
    )


def downgrade() -> None:
    # Facts are reproducible from the preserved FIT artifacts.
    op.drop_column("activity_normalization", "heart_rate_json")
