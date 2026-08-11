"""Validated application configuration."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, HttpUrl, PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded only at the application boundary."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="SWIM_COACH_",
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


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide validated settings."""

    return Settings()
