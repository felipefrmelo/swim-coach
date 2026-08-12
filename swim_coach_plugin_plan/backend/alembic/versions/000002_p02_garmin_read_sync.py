"""p02 Garmin read sync

Revision ID: 000002
Revises: 000001
Create Date: 2026-08-11 20:50:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "000002"
down_revision: str | None = "000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "garmin_connection",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("account_label_masked", sa.String(length=320), nullable=False),
        sa.Column("encrypted_token_bundle", sa.LargeBinary(), nullable=True),
        sa.Column("token_nonce", sa.LargeBinary(), nullable=True),
        sa.Column("token_key_version", sa.String(length=64), nullable=True),
        sa.Column("provider_library_version", sa.String(length=80), nullable=False),
        sa.Column("authenticated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_refresh_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=80), nullable=True),
        sa.Column("last_error_message_redacted", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "status IN ('disconnected','active','degraded','reauth_required','disabled')",
            name="ck_garmin_connection_status",
        ),
        sa.CheckConstraint(
            "(encrypted_token_bundle IS NULL AND token_nonce IS NULL AND "
            "token_key_version IS NULL) OR (encrypted_token_bundle IS NOT NULL AND "
            "token_nonce IS NOT NULL AND token_key_version IS NOT NULL)",
            name="ck_garmin_connection_secret_complete",
        ),
        sa.CheckConstraint("version >= 1", name="ck_garmin_connection_version"),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_table(
        "sync_cursor",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("entity_type", sa.String(length=50), nullable=False),
        sa.Column("cursor_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("watermark_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("overlap_seconds", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint("overlap_seconds >= 0", name="ck_sync_cursor_overlap"),
        sa.CheckConstraint("version >= 1", name="ck_sync_cursor_version"),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "provider", "entity_type", name="uq_sync_cursor_user_provider_entity"
        ),
    )
    op.create_table(
        "sync_run",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("sync_type", sa.String(length=50), nullable=False),
        sa.Column("trigger", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("listed", sa.Integer(), nullable=False),
        sa.Column("created", sa.Integer(), nullable=False),
        sa.Column("updated", sa.Integer(), nullable=False),
        sa.Column("skipped", sa.Integer(), nullable=False),
        sa.Column("failed", sa.Integer(), nullable=False),
        sa.Column("cursor_before_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("cursor_after_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("error_json_redacted", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "status IN ('running','succeeded','partial','failed','cancelled')",
            name="ck_sync_run_status",
        ),
        sa.CheckConstraint(
            "listed >= 0 AND created >= 0 AND updated >= 0 AND skipped >= 0 AND failed >= 0",
            name="ck_sync_run_counters",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_sync_run_user_started",
        "sync_run",
        ["user_id", sa.literal_column("started_at DESC")],
        unique=False,
    )
    op.create_table(
        "raw_provider_payload",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("entity_type", sa.String(length=50), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("json_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("provider_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "provider",
            "entity_type",
            "external_id",
            "checksum",
            name="uq_raw_payload_identity_checksum",
        ),
    )
    op.create_index(
        "ix_raw_payload_user_received",
        "raw_provider_payload",
        ["user_id", sa.literal_column("received_at DESC")],
        unique=False,
    )
    op.create_table(
        "activity",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("external_activity_id", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("sport", sa.String(length=50), nullable=False),
        sa.Column("subtype", sa.String(length=50), nullable=False),
        sa.Column("start_time_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("timezone", sa.String(length=100), nullable=False),
        sa.Column("distance_m", sa.Integer(), nullable=False),
        sa.Column("elapsed_seconds", sa.Numeric(14, 3), nullable=False),
        sa.Column("timer_seconds", sa.Numeric(14, 3), nullable=False),
        sa.Column("moving_seconds", sa.Numeric(14, 3), nullable=False),
        sa.Column("pool_length_m", sa.Integer(), nullable=True),
        sa.Column("length_count", sa.Integer(), nullable=True),
        sa.Column("calories", sa.Integer(), nullable=True),
        sa.Column("avg_hr", sa.Integer(), nullable=True),
        sa.Column("max_hr", sa.Integer(), nullable=True),
        sa.Column("avg_pace_seconds_per_100m", sa.Numeric(14, 3), nullable=True),
        sa.Column("avg_stroke_rate", sa.Numeric(14, 3), nullable=True),
        sa.Column("avg_strokes_per_length", sa.Numeric(14, 3), nullable=True),
        sa.Column("avg_swolf", sa.Numeric(14, 3), nullable=True),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("normalization_version", sa.String(length=64), nullable=True),
        sa.Column("raw_summary_id", sa.Uuid(), nullable=False),
        sa.Column("raw_fit_id", sa.Uuid(), nullable=True),
        sa.Column("summary_checksum", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "distance_m >= 0 AND elapsed_seconds >= 0 AND timer_seconds >= 0 "
            "AND moving_seconds >= 0",
            name="ck_activity_non_negative_totals",
        ),
        sa.CheckConstraint("pool_length_m IS NULL OR pool_length_m > 0", name="ck_activity_pool"),
        sa.ForeignKeyConstraint(["raw_fit_id"], ["raw_provider_payload.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["raw_summary_id"], ["raw_provider_payload.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "provider", "external_activity_id", name="uq_activity_user_external"
        ),
    )
    op.create_index(
        "ix_activity_user_start",
        "activity",
        ["user_id", sa.literal_column("start_time_utc DESC")],
        unique=False,
    )
    op.create_table(
        "activity_import",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("sync_run_id", sa.Uuid(), nullable=False),
        sa.Column("activity_id", sa.Uuid(), nullable=True),
        sa.Column("external_activity_id", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('created','updated','skipped','failed')",
            name="ck_activity_import_status",
        ),
        sa.ForeignKeyConstraint(["activity_id"], ["activity.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["sync_run_id"], ["sync_run.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "sync_run_id", "external_activity_id", name="uq_activity_import_run_external"
        ),
    )
    op.create_index(
        "ix_activity_import_user_created",
        "activity_import",
        ["user_id", sa.literal_column("created_at DESC")],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_activity_import_user_created", table_name="activity_import")
    op.drop_table("activity_import")
    op.drop_index("ix_activity_user_start", table_name="activity")
    op.drop_table("activity")
    op.drop_index("ix_raw_payload_user_received", table_name="raw_provider_payload")
    op.drop_table("raw_provider_payload")
    op.drop_index("ix_sync_run_user_started", table_name="sync_run")
    op.drop_table("sync_run")
    op.drop_table("sync_cursor")
    op.drop_table("garmin_connection")
