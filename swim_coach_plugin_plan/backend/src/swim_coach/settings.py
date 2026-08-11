"""Validated application configuration."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, HttpUrl, PostgresDsn, model_validator
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

    @model_validator(mode="after")
    def validate_oauth_metadata(self) -> "Settings":
        """Require a complete HTTPS resource/issuer pair when OAuth is advertised."""

        if (self.oauth_issuer is None) != (self.oauth_resource is None):
            raise ValueError("oauth_issuer and oauth_resource must be configured together")
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
        return self


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide validated settings."""

    return Settings()
