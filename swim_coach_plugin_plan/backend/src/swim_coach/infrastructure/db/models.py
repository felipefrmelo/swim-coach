"""SQLAlchemy mappings for the P01 transactional foundation."""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class AppUserModel(Base):
    __tablename__ = "app_user"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    locale: Mapped[str] = mapped_column(String(35), nullable=False)
    timezone: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (
        CheckConstraint("status IN ('active','disabled','deleted')", name="ck_app_user_status"),
        CheckConstraint("version >= 1", name="ck_app_user_version"),
        Index("uq_app_user_email_ci", text("lower(email)"), unique=True),
    )


class AuthIdentityModel(Base):
    __tablename__ = "auth_identity"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    claims_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (
        UniqueConstraint("provider", "subject", name="uq_auth_identity_provider_subject"),
        Index("ix_auth_identity_user", "user_id"),
    )


class PoolModel(Base):
    __tablename__ = "pool"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    length_m: Mapped[int] = mapped_column(Integer, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    location_label: Mapped[str | None] = mapped_column(String(160))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (
        CheckConstraint("length_m > 0", name="ck_pool_length_positive"),
        CheckConstraint("version >= 1", name="ck_pool_version"),
        Index("ix_pool_user", "user_id"),
        Index(
            "uq_pool_one_default_per_user",
            "user_id",
            unique=True,
            postgresql_where=text("is_default"),
        ),
    )


class AthleteProfileModel(Base):
    __tablename__ = "athlete_profile"

    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True
    )
    experience_level: Mapped[str] = mapped_column(String(40), nullable=False)
    preferred_distance_unit: Mapped[str] = mapped_column(String(10), nullable=False)
    default_pool_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("pool.id", ondelete="SET NULL")
    )
    default_sessions_per_week: Mapped[int] = mapped_column(Integer, nullable=False)
    goal_notes: Mapped[str | None] = mapped_column(Text)
    coach_preferences_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (
        CheckConstraint(
            "default_sessions_per_week BETWEEN 1 AND 14",
            name="ck_athlete_profile_sessions",
        ),
        CheckConstraint("preferred_distance_unit = 'm'", name="ck_athlete_profile_unit"),
        CheckConstraint("version >= 1", name="ck_athlete_profile_version"),
    )


class AvailabilityRuleModel(Base):
    __tablename__ = "availability_rule"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    day_of_week: Mapped[int] = mapped_column(Integer, nullable=False)
    start_local_time: Mapped[time] = mapped_column(Time(timezone=False), nullable=False)
    end_local_time: Mapped[time] = mapped_column(Time(timezone=False), nullable=False)
    max_duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    pool_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("pool.id", ondelete="SET NULL")
    )
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_until: Mapped[date | None] = mapped_column(Date)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (
        CheckConstraint("day_of_week BETWEEN 0 AND 6", name="ck_availability_weekday"),
        CheckConstraint("start_local_time < end_local_time", name="ck_availability_time"),
        CheckConstraint("max_duration_minutes > 0", name="ck_availability_duration"),
        CheckConstraint(
            "valid_until IS NULL OR valid_from IS NULL OR valid_from <= valid_until",
            name="ck_availability_validity",
        ),
        Index("ix_availability_user_day", "user_id", "day_of_week"),
    )


class AthleteConstraintModel(Base):
    __tablename__ = "athlete_constraint"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[str] = mapped_column(String(40), nullable=False)
    severity: Mapped[int] = mapped_column(Integer, nullable=False)
    active_from: Mapped[date] = mapped_column(Date, nullable=False)
    active_until: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (
        CheckConstraint("severity BETWEEN 1 AND 5", name="ck_athlete_constraint_severity"),
        CheckConstraint(
            "active_until IS NULL OR active_from <= active_until",
            name="ck_athlete_constraint_dates",
        ),
        Index("ix_athlete_constraint_user_active", "user_id", "is_active"),
    )


class DeviceModel(Base):
    __tablename__ = "device"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    external_device_id: Mapped[str] = mapped_column(String(255), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    serial_hash: Mapped[str | None] = mapped_column(String(128))
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    capabilities_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (
        UniqueConstraint("provider", "external_device_id", name="uq_device_provider_external"),
        Index("ix_device_user", "user_id"),
    )


class TrainingGoalModel(Base):
    __tablename__ = "training_goal"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    target_distance_m: Mapped[int] = mapped_column(Integer, nullable=False)
    target_duration_seconds: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    target_date: Mapped[date | None] = mapped_column(Date)
    target_pace_seconds_per_100m: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    baseline_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (
        CheckConstraint("target_distance_m > 0", name="ck_training_goal_distance"),
        CheckConstraint("target_duration_seconds > 0", name="ck_training_goal_duration"),
        CheckConstraint("target_pace_seconds_per_100m > 0", name="ck_training_goal_pace"),
        CheckConstraint(
            "status IN ('draft','active','completed','cancelled')", name="ck_goal_status"
        ),
        Index("ix_training_goal_user_status", "user_id", "status"),
    )


class GoalMilestoneModel(Base):
    __tablename__ = "goal_milestone"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    goal_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("training_goal.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    target_date: Mapped[date | None] = mapped_column(Date)
    target_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (Index("ix_goal_milestone_goal", "goal_id"),)


class JobModel(Base):
    __tablename__ = "job"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE")
    )
    job_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    idempotency_key: Mapped[str | None] = mapped_column(String(200), unique=True)
    locked_by: Mapped[str | None] = mapped_column(String(120))
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_json_redacted: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (
        CheckConstraint("attempts >= 0 AND max_attempts >= 1", name="ck_job_attempts"),
        CheckConstraint(
            "status IN ('QUEUED','LEASED','RUNNING','SUCCEEDED','RETRY_SCHEDULED',"
            "'FAILED_TERMINAL','NEEDS_RECONCILIATION')",
            name="ck_job_status",
        ),
        Index(
            "ix_job_available",
            "status",
            "available_at",
            text("priority DESC"),
            postgresql_where=text("status IN ('QUEUED','RETRY_SCHEDULED')"),
        ),
    )


class NotificationModel(Base):
    __tablename__ = "notification"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    notification_type: Mapped[str] = mapped_column(String(60), nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(200), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    body: Mapped[str] = mapped_column(String(500), nullable=False)
    link: Mapped[str | None] = mapped_column(String(500))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "dedupe_key", name="uq_notification_user_dedupe"),
        Index("ix_notification_user_created", "user_id", "created_at"),
    )


class DataExportModel(Base):
    __tablename__ = "data_export"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    storage_key: Mapped[str | None] = mapped_column(String(1024))
    checksum: Mapped[str | None] = mapped_column(String(64))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING','READY','EXPIRED','FAILED')", name="ck_data_export_status"
        ),
        Index("ix_data_export_user_created", "user_id", "created_at"),
    )


class DeletionRequestModel(Base):
    __tablename__ = "deletion_request"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    execute_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "status IN ('REQUESTED','CONFIRMED','EXECUTED','CANCELLED')",
            name="ck_deletion_request_status",
        ),
        CheckConstraint("execute_after > created_at", name="ck_deletion_request_cooling_off"),
        Index("ix_deletion_request_user_created", "user_id", "created_at"),
    )


class OutboxEventModel(Base):
    __tablename__ = "outbox_event"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    aggregate_type: Mapped[str] = mapped_column(String(100), nullable=False)
    aggregate_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    aggregate_version: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(160), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE")
    )
    correlation_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    causation_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index(
            "ix_outbox_unpublished",
            "occurred_at",
            postgresql_where=text("published_at IS NULL"),
        ),
    )


class AuditEventModel(Base):
    __tablename__ = "audit_event"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    actor_type: Mapped[str] = mapped_column(String(40), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(255), nullable=False)
    action: Mapped[str] = mapped_column(String(160), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    before_json_redacted: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after_json_redacted: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    correlation_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    ip_hash: Mapped[str | None] = mapped_column(String(128))
    user_agent_summary: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_audit_event_user_created", "user_id", text("created_at DESC")),
        Index("ix_audit_event_correlation", "correlation_id"),
    )


class McpToolInvocationModel(Base):
    __tablename__ = "mcp_tool_invocation"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False)
    request_id: Mapped[str] = mapped_column(String(100), nullable=False)
    args_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    correlation_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    causation_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    error_code: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("latency_ms >= 0", name="ck_mcp_invocation_latency"),
        CheckConstraint(
            "outcome IN ('OK','NOT_FOUND','PARTIAL','FAILED')",
            name="ck_mcp_invocation_outcome",
        ),
        Index("ix_mcp_invocation_user_created", "user_id", text("created_at DESC")),
        Index("ix_mcp_invocation_tool_created", "tool_name", text("created_at DESC")),
        Index("ix_mcp_invocation_correlation", "correlation_id"),
        Index("ix_mcp_invocation_causation", "causation_id"),
    )


class ApiIdempotencyRecordModel(Base):
    __tablename__ = "api_idempotency_record"

    scope: Mapped[str] = mapped_column(String(160), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    response_status: Mapped[int] = mapped_column(Integer, nullable=False)
    response_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("expires_at > created_at", name="ck_idempotency_expiry"),
        Index("ix_idempotency_expiry", "expires_at"),
    )


class WebSessionModel(Base):
    __tablename__ = "web_session"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    csrf_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index(
            "ix_web_session_active",
            "token_hash",
            "expires_at",
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )


class OidcLoginAttemptModel(Base):
    __tablename__ = "oidc_login_attempt"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    state_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    code_verifier: Mapped[str] = mapped_column(String(160), nullable=False)
    nonce: Mapped[str] = mapped_column(String(160), nullable=False)
    redirect_uri: Mapped[str] = mapped_column(String(2048), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index(
            "ix_oidc_login_attempt_active",
            "state_hash",
            "expires_at",
            postgresql_where=text("consumed_at IS NULL"),
        ),
    )


class GarminConnectionModel(Base):
    __tablename__ = "garmin_connection"

    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    account_label_masked: Mapped[str] = mapped_column(String(320), nullable=False)
    encrypted_token_bundle: Mapped[bytes | None] = mapped_column(LargeBinary)
    token_nonce: Mapped[bytes | None] = mapped_column(LargeBinary)
    token_key_version: Mapped[str | None] = mapped_column(String(64))
    provider_library_version: Mapped[str] = mapped_column(String(80), nullable=False)
    authenticated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_refresh_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(80))
    last_error_message_redacted: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (
        CheckConstraint(
            "status IN ('disconnected','active','degraded','reauth_required','disabled')",
            name="ck_garmin_connection_status",
        ),
        CheckConstraint(
            "(encrypted_token_bundle IS NULL AND token_nonce IS NULL AND "
            "token_key_version IS NULL) OR (encrypted_token_bundle IS NOT NULL AND "
            "token_nonce IS NOT NULL AND token_key_version IS NOT NULL)",
            name="ck_garmin_connection_secret_complete",
        ),
        CheckConstraint("version >= 1", name="ck_garmin_connection_version"),
    )


class SyncCursorModel(Base):
    __tablename__ = "sync_cursor"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    cursor_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    watermark_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    overlap_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (
        UniqueConstraint(
            "user_id", "provider", "entity_type", name="uq_sync_cursor_user_provider_entity"
        ),
        CheckConstraint("overlap_seconds >= 0", name="ck_sync_cursor_overlap"),
        CheckConstraint("version >= 1", name="ck_sync_cursor_version"),
    )


class SyncRunModel(Base):
    __tablename__ = "sync_run"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    sync_type: Mapped[str] = mapped_column(String(50), nullable=False)
    trigger: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    listed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cursor_before_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    cursor_after_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    error_json_redacted: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (
        CheckConstraint(
            "status IN ('running','succeeded','partial','failed','cancelled')",
            name="ck_sync_run_status",
        ),
        CheckConstraint(
            "listed >= 0 AND created >= 0 AND updated >= 0 AND skipped >= 0 AND failed >= 0",
            name="ck_sync_run_counters",
        ),
        Index("ix_sync_run_user_started", "user_id", text("started_at DESC")),
    )


class RawProviderPayloadModel(Base):
    __tablename__ = "raw_provider_payload"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    json_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "provider",
            "entity_type",
            "external_id",
            "checksum",
            name="uq_raw_payload_identity_checksum",
        ),
        Index("ix_raw_payload_user_received", "user_id", text("received_at DESC")),
    )


class ActivityModel(Base):
    __tablename__ = "activity"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    external_activity_id: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    sport: Mapped[str] = mapped_column(String(50), nullable=False)
    subtype: Mapped[str] = mapped_column(String(50), nullable=False)
    start_time_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    timezone: Mapped[str] = mapped_column(String(100), nullable=False)
    distance_m: Mapped[int] = mapped_column(Integer, nullable=False)
    elapsed_seconds: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    timer_seconds: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    moving_seconds: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    pool_length_m: Mapped[int | None] = mapped_column(Integer)
    length_count: Mapped[int | None] = mapped_column(Integer)
    calories: Mapped[int | None] = mapped_column(Integer)
    avg_hr: Mapped[int | None] = mapped_column(Integer)
    max_hr: Mapped[int | None] = mapped_column(Integer)
    avg_pace_seconds_per_100m: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    avg_stroke_rate: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    avg_strokes_per_length: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    avg_swolf: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    normalization_version: Mapped[str | None] = mapped_column(String(64))
    raw_summary_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("raw_provider_payload.id", ondelete="RESTRICT"),
        nullable=False,
    )
    raw_fit_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("raw_provider_payload.id", ondelete="SET NULL")
    )
    summary_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    current_normalization_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "activity_normalization.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_activity_current_normalization",
        ),
    )
    current_analysis_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "activity_analysis.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_activity_current_analysis",
        ),
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id", "provider", "external_activity_id", name="uq_activity_user_external"
        ),
        CheckConstraint(
            "distance_m >= 0 AND elapsed_seconds >= 0 AND timer_seconds >= 0 "
            "AND moving_seconds >= 0",
            name="ck_activity_non_negative_totals",
        ),
        CheckConstraint("pool_length_m IS NULL OR pool_length_m > 0", name="ck_activity_pool"),
        Index("ix_activity_user_start", "user_id", text("start_time_utc DESC")),
    )


class FileArtifactModel(Base):
    __tablename__ = "file_artifact"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    activity_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("activity.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    artifact_type: Mapped[str] = mapped_column(String(30), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    source_external_id_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("size_bytes > 0", name="ck_file_artifact_size"),
        UniqueConstraint(
            "activity_id",
            "checksum",
            "artifact_type",
            name="uq_file_artifact_activity_checksum_type",
        ),
        UniqueConstraint("storage_key", name="uq_file_artifact_storage_key"),
        Index("ix_file_artifact_activity", "activity_id", "created_at"),
    )


class ActivityNormalizationModel(Base):
    __tablename__ = "activity_normalization"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    activity_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("activity.id", ondelete="CASCADE"), nullable=False
    )
    artifact_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("file_artifact.id", ondelete="RESTRICT"), nullable=False
    )
    parser_version: Mapped[str] = mapped_column(String(160), nullable=False)
    profile_version: Mapped[str] = mapped_column(String(80), nullable=False)
    input_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    pool_length_m: Mapped[int] = mapped_column(Integer, nullable=False)
    distance_m: Mapped[int] = mapped_column(Integer, nullable=False)
    elapsed_seconds: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    timer_seconds: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    moving_seconds: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    swim_seconds: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    rest_seconds: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    stationary_seconds: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    garmin_reported_speed_m_per_s: Mapped[Decimal | None] = mapped_column(Numeric(18, 9))
    pace_from_garmin_reported_speed_seconds_per_100m: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 3)
    )
    moving_pace_seconds_per_100m: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    swim_pace_seconds_per_100m: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    timer_pace_seconds_per_100m: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    session_pace_seconds_per_100m: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    active_length_count: Mapped[int] = mapped_column(Integer, nullable=False)
    completeness: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    quality: Mapped[str] = mapped_column(String(20), nullable=False)
    warnings_json: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    provenance_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "pool_length_m > 0 AND distance_m >= 0 AND active_length_count >= 0",
            name="ck_activity_normalization_totals",
        ),
        CheckConstraint(
            "elapsed_seconds >= 0 AND timer_seconds >= 0 "
            "AND (moving_seconds IS NULL OR moving_seconds >= 0) "
            "AND (swim_seconds IS NULL OR swim_seconds >= 0) "
            "AND (rest_seconds IS NULL OR rest_seconds >= 0) "
            "AND (stationary_seconds IS NULL OR stationary_seconds >= 0)",
            name="ck_activity_normalization_durations",
        ),
        CheckConstraint(
            "(garmin_reported_speed_m_per_s IS NULL OR garmin_reported_speed_m_per_s >= 0) "
            "AND (pace_from_garmin_reported_speed_seconds_per_100m IS NULL OR "
            "pace_from_garmin_reported_speed_seconds_per_100m >= 0) "
            "AND (moving_pace_seconds_per_100m IS NULL OR "
            "moving_pace_seconds_per_100m >= 0) "
            "AND (swim_pace_seconds_per_100m IS NULL OR swim_pace_seconds_per_100m >= 0) "
            "AND (timer_pace_seconds_per_100m IS NULL OR timer_pace_seconds_per_100m >= 0) "
            "AND (session_pace_seconds_per_100m IS NULL OR session_pace_seconds_per_100m >= 0)",
            name="ck_activity_normalization_paces",
        ),
        CheckConstraint(
            "completeness BETWEEN 0 AND 1", name="ck_activity_normalization_completeness"
        ),
        CheckConstraint(
            "quality IN ('complete','partial','poor')",
            name="ck_activity_normalization_quality",
        ),
        UniqueConstraint(
            "activity_id",
            "parser_version",
            "input_checksum",
            name="uq_activity_normalization_input_version",
        ),
        Index("ix_activity_normalization_activity_created", "activity_id", "created_at"),
    )


class ActivityLapModel(Base):
    __tablename__ = "activity_lap"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    normalization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("activity_normalization.id", ondelete="CASCADE"),
        nullable=False,
    )
    lap_index: Mapped[int] = mapped_column(Integer, nullable=False)
    start_offset_seconds: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    elapsed_seconds: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    timer_seconds: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    moving_seconds: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    swim_seconds: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    rest_seconds: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    stationary_seconds: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    distance_m: Mapped[int] = mapped_column(Integer, nullable=False)
    avg_hr_bpm: Mapped[int | None] = mapped_column(Integer)
    max_hr_bpm: Mapped[int | None] = mapped_column(Integer)
    stroke_type: Mapped[str | None] = mapped_column(String(50))
    detected_stroke: Mapped[str | None] = mapped_column(String(50))
    planned_stroke: Mapped[str | None] = mapped_column(String(50))
    garmin_reported_speed_m_per_s: Mapped[Decimal | None] = mapped_column(Numeric(18, 9))
    pace_from_garmin_reported_speed_seconds_per_100m: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 3)
    )
    moving_pace_seconds_per_100m: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    swim_pace_seconds_per_100m: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    timer_pace_seconds_per_100m: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    elapsed_pace_seconds_per_100m: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    provenance_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    quality_warnings_json: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)

    __table_args__ = (
        CheckConstraint(
            "lap_index >= 0 AND distance_m >= 0", name="ck_activity_lap_index_distance"
        ),
        CheckConstraint(
            "start_offset_seconds >= 0 AND elapsed_seconds >= 0 AND timer_seconds >= 0 "
            "AND (moving_seconds IS NULL OR moving_seconds >= 0) "
            "AND (swim_seconds IS NULL OR swim_seconds >= 0) "
            "AND (rest_seconds IS NULL OR rest_seconds >= 0) "
            "AND (stationary_seconds IS NULL OR stationary_seconds >= 0)",
            name="ck_activity_lap_durations",
        ),
        CheckConstraint(
            "garmin_reported_speed_m_per_s IS NULL OR garmin_reported_speed_m_per_s >= 0",
            name="ck_activity_lap_garmin_speed",
        ),
        UniqueConstraint(
            "normalization_id", "lap_index", name="uq_activity_lap_normalization_index"
        ),
    )


class ActivityIntervalModel(Base):
    __tablename__ = "activity_interval"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    normalization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("activity_normalization.id", ondelete="CASCADE"),
        nullable=False,
    )
    interval_index: Mapped[int] = mapped_column(Integer, nullable=False)
    interval_type: Mapped[str] = mapped_column(String(20), nullable=False)
    start_offset_seconds: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    duration_seconds: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    rest_seconds: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    elapsed_seconds: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    timer_seconds: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    moving_seconds: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    swim_seconds: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    stationary_seconds: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    distance_m: Mapped[int] = mapped_column(Integer, nullable=False)
    pace_seconds_per_100m: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    garmin_reported_speed_m_per_s: Mapped[Decimal | None] = mapped_column(Numeric(18, 9))
    pace_from_garmin_reported_speed_seconds_per_100m: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 3)
    )
    moving_pace_seconds_per_100m: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    swim_pace_seconds_per_100m: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    timer_pace_seconds_per_100m: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    elapsed_pace_seconds_per_100m: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    avg_hr_bpm: Mapped[int | None] = mapped_column(Integer)
    max_hr_bpm: Mapped[int | None] = mapped_column(Integer)
    stroke_type: Mapped[str | None] = mapped_column(String(50))
    detected_stroke: Mapped[str | None] = mapped_column(String(50))
    planned_stroke: Mapped[str | None] = mapped_column(String(50))
    planned_role: Mapped[str | None] = mapped_column(String(20))
    stroke_count: Mapped[int | None] = mapped_column(Integer)
    stroke_rate: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    swolf: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    source_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    provenance_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    quality_warnings_json: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)

    __table_args__ = (
        CheckConstraint(
            "interval_type IN ('work','swim','rest','drill','unknown')",
            name="ck_activity_interval_type",
        ),
        CheckConstraint(
            "planned_role IS NULL OR planned_role IN "
            "('warmup','work','recovery','rest','cooldown','drill','other')",
            name="ck_activity_interval_planned_role",
        ),
        CheckConstraint(
            "interval_index >= 0 AND distance_m >= 0",
            name="ck_activity_interval_index_distance",
        ),
        CheckConstraint(
            "start_offset_seconds >= 0 AND duration_seconds >= 0 AND rest_seconds >= 0 "
            "AND (elapsed_seconds IS NULL OR elapsed_seconds >= 0) "
            "AND (timer_seconds IS NULL OR timer_seconds >= 0) "
            "AND (moving_seconds IS NULL OR moving_seconds >= 0) "
            "AND (swim_seconds IS NULL OR swim_seconds >= 0) "
            "AND (stationary_seconds IS NULL OR stationary_seconds >= 0)",
            name="ck_activity_interval_durations",
        ),
        CheckConstraint(
            "garmin_reported_speed_m_per_s IS NULL OR garmin_reported_speed_m_per_s >= 0",
            name="ck_activity_interval_garmin_speed",
        ),
        UniqueConstraint(
            "normalization_id", "interval_index", name="uq_activity_interval_normalization_index"
        ),
    )


class ActivityLengthModel(Base):
    __tablename__ = "activity_length"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    normalization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("activity_normalization.id", ondelete="CASCADE"),
        nullable=False,
    )
    interval_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("activity_interval.id", ondelete="CASCADE"), nullable=False
    )
    length_index: Mapped[int] = mapped_column(Integer, nullable=False)
    distance_m: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_seconds: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    length_type: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    elapsed_seconds: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    timer_seconds: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    moving_seconds: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    swim_seconds: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    rest_seconds: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    stationary_seconds: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    stroke_type: Mapped[str | None] = mapped_column(String(50))
    detected_stroke: Mapped[str | None] = mapped_column(String(50))
    planned_stroke: Mapped[str | None] = mapped_column(String(50))
    garmin_reported_speed_m_per_s: Mapped[Decimal | None] = mapped_column(Numeric(18, 9))
    pace_from_garmin_reported_speed_seconds_per_100m: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 3)
    )
    moving_pace_seconds_per_100m: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    swim_pace_seconds_per_100m: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    timer_pace_seconds_per_100m: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    elapsed_pace_seconds_per_100m: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    stroke_count: Mapped[int | None] = mapped_column(Integer)
    stroke_rate: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    swolf: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    avg_hr_bpm: Mapped[int | None] = mapped_column(Integer)
    provenance_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    quality_warnings_json: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)

    __table_args__ = (
        CheckConstraint(
            "length_index >= 0 AND distance_m >= 0 AND duration_seconds >= 0 "
            "AND length_type IN ('active','idle','unknown') "
            "AND (length_type <> 'active' OR distance_m > 0) "
            "AND (length_type <> 'idle' OR distance_m = 0) "
            "AND (elapsed_seconds IS NULL OR elapsed_seconds >= 0) "
            "AND (timer_seconds IS NULL OR timer_seconds >= 0) "
            "AND (moving_seconds IS NULL OR moving_seconds >= 0) "
            "AND (swim_seconds IS NULL OR swim_seconds >= 0) "
            "AND (rest_seconds IS NULL OR rest_seconds >= 0) "
            "AND (stationary_seconds IS NULL OR stationary_seconds >= 0)",
            name="ck_activity_length_values",
        ),
        CheckConstraint(
            "garmin_reported_speed_m_per_s IS NULL OR garmin_reported_speed_m_per_s >= 0",
            name="ck_activity_length_garmin_speed",
        ),
        UniqueConstraint(
            "normalization_id", "length_index", name="uq_activity_length_normalization_index"
        ),
    )


class ActivityAnalysisModel(Base):
    __tablename__ = "activity_analysis"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    activity_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("activity.id", ondelete="CASCADE"), nullable=False
    )
    normalization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("activity_normalization.id", ondelete="CASCADE"),
        nullable=False,
    )
    planned_workout_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("planned_workout.id", ondelete="SET NULL")
    )
    analysis_version: Mapped[str] = mapped_column(String(80), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(160), nullable=False)
    input_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    pool_length_m: Mapped[int] = mapped_column(Integer, nullable=False)
    metrics_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    flags_json: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    quality: Mapped[str] = mapped_column(String(20), nullable=False)
    summary_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("pool_length_m > 0", name="ck_activity_analysis_pool"),
        CheckConstraint(
            "quality IN ('complete','partial','poor')", name="ck_activity_analysis_quality"
        ),
        Index("ix_activity_analysis_activity_created", "activity_id", "created_at"),
        Index(
            "uq_activity_analysis_version_target",
            "normalization_id",
            "analysis_version",
            text("coalesce(planned_workout_id, '00000000-0000-0000-0000-000000000000'::uuid)"),
            unique=True,
        ),
    )


class WorkoutExecutionMatchModel(Base):
    __tablename__ = "workout_execution_match"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    activity_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("activity.id", ondelete="CASCADE"), nullable=False
    )
    planned_workout_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("planned_workout.id", ondelete="CASCADE"), nullable=False
    )
    method: Mapped[str] = mapped_column(String(20), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    score_details_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_by: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "method IN ('automatic','suggested','manual')",
            name="ck_workout_execution_match_method",
        ),
        CheckConstraint("confidence BETWEEN 0 AND 1", name="ck_workout_execution_match_confidence"),
        UniqueConstraint("activity_id", name="uq_workout_execution_match_activity"),
        UniqueConstraint("planned_workout_id", name="uq_workout_execution_match_workout"),
    )


class SessionFeedbackModel(Base):
    __tablename__ = "session_feedback"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    activity_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("activity.id", ondelete="CASCADE"), nullable=False
    )
    rpe: Mapped[int] = mapped_column(Integer, nullable=False)
    technique_rating: Mapped[int | None] = mapped_column(Integer)
    fatigue_rating: Mapped[int | None] = mapped_column(Integer)
    enjoyment_rating: Mapped[int | None] = mapped_column(Integer)
    pain_present: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    pain_location: Mapped[str | None] = mapped_column(String(120))
    pain_intensity: Mapped[int | None] = mapped_column(Integer)
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (
        CheckConstraint("rpe BETWEEN 1 AND 10", name="ck_session_feedback_rpe"),
        CheckConstraint(
            "technique_rating IS NULL OR technique_rating BETWEEN 1 AND 5",
            name="ck_session_feedback_technique",
        ),
        CheckConstraint(
            "fatigue_rating IS NULL OR fatigue_rating BETWEEN 1 AND 5",
            name="ck_session_feedback_fatigue",
        ),
        CheckConstraint(
            "enjoyment_rating IS NULL OR enjoyment_rating BETWEEN 1 AND 5",
            name="ck_session_feedback_enjoyment",
        ),
        CheckConstraint(
            "(pain_present AND pain_location IS NOT NULL AND pain_intensity BETWEEN 1 AND 10) "
            "OR (NOT pain_present AND pain_location IS NULL AND pain_intensity IS NULL)",
            name="ck_session_feedback_pain",
        ),
        CheckConstraint("version >= 1", name="ck_session_feedback_version"),
        UniqueConstraint("activity_id", name="uq_session_feedback_activity"),
    )


class ActivityImportModel(Base):
    __tablename__ = "activity_import"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    sync_run_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("sync_run.id", ondelete="CASCADE"), nullable=False
    )
    activity_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("activity.id", ondelete="SET NULL")
    )
    external_activity_id: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "sync_run_id", "external_activity_id", name="uq_activity_import_run_external"
        ),
        CheckConstraint(
            "status IN ('created','updated','skipped','failed')",
            name="ck_activity_import_status",
        ),
        Index("ix_activity_import_user_created", "user_id", text("created_at DESC")),
    )


class WorkoutTemplateModel(Base):
    __tablename__ = "workout_template"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    owner_user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    objective: Mapped[str] = mapped_column(String(500), nullable=False)
    tags_json: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    definition_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(20), nullable=False)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_workout_template_owner_active", "owner_user_id", "active"),)


class PlannedWorkoutModel(Base):
    __tablename__ = "planned_workout"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    sport: Mapped[str] = mapped_column(String(30), nullable=False, default="POOL_SWIMMING")
    purpose: Mapped[str] = mapped_column(String(30), nullable=False)
    pool_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("pool.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    current_revision_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    approved_revision_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    source: Mapped[str] = mapped_column(String(30), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (
        CheckConstraint("sport = 'POOL_SWIMMING'", name="ck_planned_workout_sport"),
        CheckConstraint(
            "status IN ('draft','approved','scheduled','published','completed',"
            "'cancelled','archived','deleting')",
            name="ck_planned_workout_status",
        ),
        CheckConstraint("version >= 1", name="ck_planned_workout_version"),
        Index("ix_planned_workout_user_status", "user_id", "status"),
    )


class WorkoutRevisionModel(Base):
    __tablename__ = "workout_revision"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    workout_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("planned_workout.id", ondelete="CASCADE"), nullable=False
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    definition_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    total_distance_m: Mapped[int] = mapped_column(Integer, nullable=False)
    estimated_active_seconds: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    estimated_rest_seconds: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    estimated_total_seconds: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    distance_steps: Mapped[int] = mapped_column(Integer, nullable=False)
    executable_steps: Mapped[int] = mapped_column(Integer, nullable=False)
    lengths: Mapped[int] = mapped_column(Integer, nullable=False)
    validation_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    change_reason: Mapped[str | None] = mapped_column(String(500))
    created_by_type: Mapped[str] = mapped_column(String(30), nullable=False)
    created_by_id: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("workout_id", "revision_number", name="uq_workout_revision_number"),
        CheckConstraint("revision_number >= 1", name="ck_workout_revision_number"),
        CheckConstraint("total_distance_m >= 0", name="ck_workout_revision_distance"),
        Index("ix_workout_revision_workout_created", "workout_id", "created_at"),
    )


class WorkoutScheduleModel(Base):
    __tablename__ = "workout_schedule"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    workout_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("planned_workout.id", ondelete="CASCADE"), nullable=False
    )
    scheduled_date: Mapped[date] = mapped_column(Date, nullable=False)
    scheduled_start_time: Mapped[time | None] = mapped_column(Time(timezone=False))
    timezone: Mapped[str] = mapped_column(String(100), nullable=False)
    pool_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("pool.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("workout_id", name="uq_workout_schedule_workout"),
        Index("ix_workout_schedule_date", "scheduled_date"),
    )


class ActionProposalModel(Base):
    __tablename__ = "action_proposal"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    action_type: Mapped[str] = mapped_column(String(100), nullable=False)
    target_type: Mapped[str] = mapped_column(String(100), nullable=False)
    target_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    target_revision_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workout_revision.id", ondelete="RESTRICT")
    )
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    impact_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    action_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (
        UniqueConstraint("user_id", "action_hash", name="uq_action_proposal_user_hash"),
        CheckConstraint(
            "status IN ('DRAFT','READY_FOR_REVIEW','APPROVED','REJECTED','EXPIRED',"
            "'QUEUED','EXECUTING','SUCCEEDED','FAILED','NEEDS_RECONCILIATION','CANCELLED')",
            name="ck_action_proposal_status",
        ),
        CheckConstraint("expires_at > created_at", name="ck_action_proposal_expiry"),
        CheckConstraint("version >= 1", name="ck_action_proposal_version"),
        Index("ix_action_proposal_user_status", "user_id", "status", "created_at"),
        Index("ix_action_proposal_target", "target_type", "target_id"),
    )


class ActionApprovalModel(Base):
    __tablename__ = "action_approval"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    proposal_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("action_proposal.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    action_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    decision: Mapped[str] = mapped_column(String(10), nullable=False)
    explicit_verb: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("proposal_id", name="uq_action_approval_proposal"),
        CheckConstraint("decision IN ('APPROVE','REJECT')", name="ck_action_approval_decision"),
        Index("ix_action_approval_user_created", "user_id", "created_at"),
    )


class TrainingRuleSetModel(Base):
    __tablename__ = "training_rule_set"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    version: Mapped[str] = mapped_column(String(40), nullable=False)
    rules_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(20), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_until: Mapped[date | None] = mapped_column(Date)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_training_rule_set_name_version"),
        UniqueConstraint("content_hash", name="uq_training_rule_set_hash"),
        CheckConstraint(
            "effective_until IS NULL OR effective_until >= effective_from",
            name="ck_training_rule_set_effective_range",
        ),
        Index("ix_training_rule_set_effective", "effective_from", "effective_until"),
    )


class PlanningRunModel(Base):
    __tablename__ = "planning_run"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    goal_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("training_goal.id", ondelete="RESTRICT"), nullable=False
    )
    rule_set_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("training_rule_set.id", ondelete="RESTRICT"), nullable=False
    )
    week_start: Mapped[date] = mapped_column(Date, nullable=False)
    input_snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    output_plan_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    output_proposal_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("action_proposal.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    warnings_json: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint(
            "user_id", "rule_set_id", "input_hash", name="uq_planning_run_reproducible_input"
        ),
        CheckConstraint("status IN ('COMPLETED','FAILED')", name="ck_planning_run_status"),
        Index("ix_planning_run_user_week", "user_id", "week_start", "created_at"),
    )


class TrainingDecisionModel(Base):
    __tablename__ = "training_decision"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    planning_run_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("planning_run.id", ondelete="CASCADE"), nullable=False
    )
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    decision_type: Mapped[str] = mapped_column(String(100), nullable=False)
    rule_id: Mapped[str] = mapped_column(String(100), nullable=False)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    evidence_refs_json: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    before_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    after_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    rationale: Mapped[str] = mapped_column(String(1000), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(30), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("planning_run_id", "order_index", name="uq_training_decision_run_order"),
        CheckConstraint("order_index >= 1", name="ck_training_decision_order"),
        Index("ix_training_decision_user_date", "user_id", "effective_date"),
    )


class ActionExecutionModel(Base):
    __tablename__ = "action_execution"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    proposal_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("action_proposal.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error_json_redacted: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (
        UniqueConstraint("proposal_id", name="uq_action_execution_proposal"),
        UniqueConstraint("idempotency_key", name="uq_action_execution_idempotency"),
        CheckConstraint(
            "status IN ('QUEUED','EXECUTING','SUCCEEDED','FAILED',"
            "'NEEDS_RECONCILIATION','CANCELLED')",
            name="ck_action_execution_status",
        ),
        CheckConstraint("version >= 1", name="ck_action_execution_version"),
        Index("ix_action_execution_user_status", "user_id", "status"),
    )


class ExternalWorkoutBindingModel(Base):
    __tablename__ = "external_workout_binding"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    workout_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("planned_workout.id", ondelete="CASCADE"), nullable=False
    )
    revision_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workout_revision.id", ondelete="RESTRICT"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    compiled_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    external_workout_id: Mapped[str | None] = mapped_column(String(255))
    external_schedule_id: Mapped[str | None] = mapped_column(String(255))
    scheduled_date: Mapped[date | None] = mapped_column(Date)
    last_error_json_redacted: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "provider",
            "workout_id",
            "revision_id",
            "compiled_hash",
            name="uq_external_workout_binding_revision_hash",
        ),
        UniqueConstraint(
            "user_id",
            "provider",
            "external_workout_id",
            name="uq_external_workout_binding_external",
        ),
        CheckConstraint(
            "status IN ('NOT_CREATED','CREATING','CREATED','SCHEDULING','SCHEDULED',"
            "'FAILED','NEEDS_RECONCILIATION')",
            name="ck_external_workout_binding_status",
        ),
        CheckConstraint("version >= 1", name="ck_external_workout_binding_version"),
        Index("ix_external_workout_binding_user_status", "user_id", "status"),
    )
