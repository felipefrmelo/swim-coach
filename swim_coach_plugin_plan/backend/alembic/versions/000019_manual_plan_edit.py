"""Allow explicitly approved manual plan edits, preserving revision history."""

import sqlalchemy as sa
from alembic import op

revision = "000019"
down_revision = "000018"
branch_labels = None
depends_on = None


def _constraint(kinds: str) -> None:
    op.drop_constraint("ck_training_plan_revision_kind", "training_plan_revision", type_="check")
    op.create_check_constraint(
        "ck_training_plan_revision_kind", "training_plan_revision", f"revision_kind IN ({kinds})"
    )


def upgrade() -> None:
    _constraint("'CREATION','ADAPTATION','MATERIALIZATION','LEGACY','RESCHEDULE','MANUAL_EDIT'")


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text("SELECT count(*) FROM training_plan_revision WHERE revision_kind='MANUAL_EDIT'")
    ):
        raise RuntimeError("Manual plan revisions exist; preserve history and migrate forward.")
    _constraint("'CREATION','ADAPTATION','MATERIALIZATION','LEGACY','RESCHEDULE'")
