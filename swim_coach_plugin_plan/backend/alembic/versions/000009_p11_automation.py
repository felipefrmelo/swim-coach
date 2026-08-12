"""P11 automation notifications.

Revision ID: 000009
Revises: 000008
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "000009"
down_revision: str | None = "000008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "notification",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("notification_type", sa.String(60), nullable=False),
        sa.Column("dedupe_key", sa.String(200), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("body", sa.String(500), nullable=False),
        sa.Column("link", sa.String(500), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "dedupe_key", name="uq_notification_user_dedupe"),
    )
    op.create_index("ix_notification_user_created", "notification", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_notification_user_created", table_name="notification")
    op.drop_table("notification")
