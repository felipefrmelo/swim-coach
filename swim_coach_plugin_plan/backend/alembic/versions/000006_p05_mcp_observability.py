"""P05 sanitized MCP invocation observability.

Revision ID: 000006
Revises: 000005
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "000006"
down_revision: str | None = "000005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mcp_tool_invocation",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("tool_name", sa.String(length=100), nullable=False),
        sa.Column("request_id", sa.String(length=100), nullable=False),
        sa.Column("args_hash", sa.String(length=64), nullable=False),
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("latency_ms >= 0", name="ck_mcp_invocation_latency"),
        sa.CheckConstraint(
            "outcome IN ('OK','NOT_FOUND','PARTIAL','FAILED')",
            name="ck_mcp_invocation_outcome",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_mcp_invocation_user_created",
        "mcp_tool_invocation",
        ["user_id", "created_at"],
    )
    op.create_index(
        "ix_mcp_invocation_tool_created",
        "mcp_tool_invocation",
        ["tool_name", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_mcp_invocation_tool_created", table_name="mcp_tool_invocation")
    op.drop_index("ix_mcp_invocation_user_created", table_name="mcp_tool_invocation")
    op.drop_table("mcp_tool_invocation")
