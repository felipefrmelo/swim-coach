"""Validated application configuration."""

import base64
import binascii
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, HttpUrl, PostgresDsn, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded only at the application boundary."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="SWIM_COACH_",
        env_ignore_empty=True,
        extra="ignore",
    )

    environment: Literal["development", "test", "production"] = "development"
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    database_url: PostgresDsn = PostgresDsn(
        "postgresql://swim_coach:local_only@localhost:5432/swim_coach"
    )
    public_base_url: HttpUrl | None = None
    oauth_issuer: HttpUrl | None = None
    oauth_resource: HttpUrl | None = None
    oauth_jwks_cache_seconds: int = Field(default=300, ge=30, le=3_600)
    mcp_write_enabled: bool = False
    mcp_v2_enabled: bool = True
    mcp_ui_enabled: bool = False
    planning_enabled: bool = False
    automation_enabled: bool = False
    automation_sync_hour: int = Field(default=6, ge=0, le=23)
    automation_planning_weekday: int = Field(default=6, ge=0, le=6)
    automation_planning_hour: int = Field(default=18, ge=0, le=23)
    job_retention_days: int = Field(default=30, ge=7, le=365)
    api_read_rate_limit_per_minute: int = Field(default=120, ge=1, le=10_000)
    api_write_rate_limit_per_minute: int = Field(default=30, ge=1, le=1_000)
    api_max_body_bytes: int = Field(default=1_048_576, ge=1_024, le=10_485_760)
    pwa_base_url: HttpUrl = HttpUrl("http://127.0.0.1:14173")
    oidc_issuer: HttpUrl | None = None
    oidc_client_id: str | None = None
    oidc_client_secret: SecretStr | None = None
    auth_allowed_emails: str = ""
    auth_allowed_subjects: str = ""
    dev_auth_enabled: bool = False
    dev_auth_email: str = "local-swimmer@example.test"
    session_lifetime_hours: int = Field(default=8, ge=1, le=24)
    garmin_master_keys: SecretStr | None = None
    garmin_active_key_version: str | None = None
    garmin_sync_lookback_days: int = Field(default=90, ge=1, le=365)
    garmin_sync_overlap_seconds: int = Field(default=172_800, ge=0, le=604_800)
    garmin_read_enabled: bool = True
    garmin_write_enabled: bool = False
    garmin_write_mode: Literal["disabled", "fake", "live"] = "disabled"
    activity_storage_path: Path = Path(".swim-coach-data/artifacts")

    @model_validator(mode="after")
    def validate_oauth_metadata(self) -> "Settings":
        """Require a complete HTTPS resource/issuer pair when OAuth is advertised."""

        if (self.oauth_issuer is None) != (self.oauth_resource is None):
            raise ValueError("oauth_issuer and oauth_resource must be configured together")
        if self.mcp_write_enabled and self.oauth_issuer is None:
            raise ValueError("mcp_write_enabled requires OAuth issuer and resource metadata")
        if self.mcp_ui_enabled and not self.mcp_write_enabled:
            raise ValueError("mcp_ui_enabled requires the complete controlled-write surface")
        if self.oauth_issuer is not None and self.oauth_issuer.scheme != "https":
            raise ValueError("oauth_issuer must use HTTPS")
        if self.oauth_resource is not None and self.oauth_resource.scheme != "https":
            loopback_hosts = {"127.0.0.1", "localhost", "[::1]"}
            is_development_loopback = (
                self.environment != "production"
                and self.oauth_resource.scheme == "http"
                and self.oauth_resource.host in loopback_hosts
            )
            if not is_development_loopback:
                raise ValueError(
                    "oauth_resource must use HTTPS except for HTTP loopback outside production"
                )
        if (self.oidc_issuer is None) != (self.oidc_client_id is None):
            raise ValueError("oidc_issuer and oidc_client_id must be configured together")
        if self.oidc_issuer is not None and self.oidc_issuer.scheme != "https":
            raise ValueError("oidc_issuer must use HTTPS")
        if self.environment == "production":
            if self.dev_auth_enabled:
                raise ValueError("dev_auth_enabled is forbidden in production")
            if self.pwa_base_url.scheme != "https":
                raise ValueError("pwa_base_url must use HTTPS in production")
        if self.dev_auth_enabled and self.dev_auth_email.casefold() not in self.allowed_emails:
            raise ValueError("dev_auth_email must be explicitly allowlisted")
        if (self.garmin_master_keys is None) != (self.garmin_active_key_version is None):
            raise ValueError(
                "garmin_master_keys and garmin_active_key_version must be configured together"
            )
        if self.garmin_master_keys is not None:
            keyring = self.garmin_keyring
            if self.garmin_active_key_version not in keyring:
                raise ValueError("garmin_active_key_version is not present in garmin_master_keys")
        if self.garmin_write_enabled and self.garmin_write_mode == "disabled":
            raise ValueError("garmin_write_enabled requires fake or live write mode")
        if self.environment == "production" and self.garmin_write_mode == "fake":
            raise ValueError("fake Garmin writes are forbidden in production")
        if (
            self.garmin_write_enabled
            and self.garmin_write_mode == "live"
            and self.garmin_master_keys is None
        ):
            raise ValueError("live Garmin writes require encrypted Garmin credentials")
        if (self.dev_auth_enabled or self.oidc_issuer is not None) and not (
            self.allowed_emails or self.allowed_subjects
        ):
            raise ValueError(
                "an email or subject allowlist is required when authentication is enabled"
            )
        return self

    @property
    def allowed_emails(self) -> frozenset[str]:
        return frozenset(
            item.strip().casefold() for item in self.auth_allowed_emails.split(",") if item.strip()
        )

    @property
    def allowed_subjects(self) -> frozenset[str]:
        return frozenset(
            item.strip() for item in self.auth_allowed_subjects.split(",") if item.strip()
        )

    @property
    def oidc_redirect_uri(self) -> str:
        return f"{str(self.pwa_base_url).rstrip('/')}/api/v1/auth/callback"

    @property
    def garmin_keyring(self) -> dict[str, bytes]:
        if self.garmin_master_keys is None:
            return {}
        result: dict[str, bytes] = {}
        for entry in self.garmin_master_keys.get_secret_value().split(","):
            version, separator, encoded = entry.strip().partition(":")
            if not separator or not version or version in result:
                raise ValueError("garmin_master_keys entries must use unique version:base64 values")
            try:
                padding = "=" * (-len(encoded) % 4)
                key = base64.urlsafe_b64decode(encoded + padding)
            except (ValueError, binascii.Error) as exc:
                raise ValueError("garmin_master_keys contains invalid base64") from exc
            if len(key) != 32:
                raise ValueError("each Garmin master key must contain exactly 32 bytes")
            result[version] = key
        return result


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide validated settings."""

    return Settings()
