"""P08 MCP write correlation and causation trace.

Revision ID: 000007
Revises: 000006
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "000007"
down_revision: str | None = "000006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("mcp_tool_invocation", sa.Column("correlation_id", sa.Uuid(), nullable=True))
    op.add_column("mcp_tool_invocation", sa.Column("causation_id", sa.Uuid(), nullable=True))
    op.create_index("ix_mcp_invocation_correlation", "mcp_tool_invocation", ["correlation_id"])
    op.create_index("ix_mcp_invocation_causation", "mcp_tool_invocation", ["causation_id"])


def downgrade() -> None:
    op.drop_index("ix_mcp_invocation_causation", table_name="mcp_tool_invocation")
    op.drop_index("ix_mcp_invocation_correlation", table_name="mcp_tool_invocation")
    op.drop_column("mcp_tool_invocation", "causation_id")
    op.drop_column("mcp_tool_invocation", "correlation_id")
