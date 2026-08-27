"""P14 hidden deleting state for asynchronous Garmin cleanup.

Revision ID: 000011
Revises: 000010
"""

from collections.abc import Sequence

from alembic import op

revision: str = "000011"
down_revision: str | None = "000010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_planned_workout_status", "planned_workout", type_="check")
    op.create_check_constraint(
        "ck_planned_workout_status",
        "planned_workout",
        "status IN ('draft','approved','scheduled','published','completed',"
        "'cancelled','archived','deleting')",
    )


def downgrade() -> None:
    op.execute("UPDATE planned_workout SET status = 'cancelled' WHERE status = 'deleting'")
    op.drop_constraint("ck_planned_workout_status", "planned_workout", type_="check")
    op.create_check_constraint(
        "ck_planned_workout_status",
        "planned_workout",
        "status IN ('draft','approved','scheduled','published','completed','cancelled','archived')",
    )
