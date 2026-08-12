"""P12 export and staged deletion records.

Revision ID: 000010
Revises: 000009
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "000010"
down_revision: str | None = "000009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "data_export",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("storage_key", sa.String(1024), nullable=True),
        sa.Column("checksum", sa.String(64), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('PENDING','READY','EXPIRED','FAILED')", name="ck_data_export_status"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_data_export_user_created", "data_export", ["user_id", "created_at"])
    op.create_table(
        "deletion_request",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("execute_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('REQUESTED','CONFIRMED','EXECUTED','CANCELLED')",
            name="ck_deletion_request_status",
        ),
        sa.CheckConstraint("execute_after > created_at", name="ck_deletion_request_cooling_off"),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_deletion_request_user_created", "deletion_request", ["user_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_deletion_request_user_created", table_name="deletion_request")
    op.drop_table("deletion_request")
    op.drop_index("ix_data_export_user_created", table_name="data_export")
    op.drop_table("data_export")
