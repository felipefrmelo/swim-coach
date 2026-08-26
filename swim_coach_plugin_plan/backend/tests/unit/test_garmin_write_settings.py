"""Garmin read/write settings."""

import base64

import pytest
from pydantic import ValidationError

from swim_coach.settings import Settings


def keyring() -> str:
    return "v1:" + base64.urlsafe_b64encode(b"x" * 32).decode().rstrip("=")


def test_write_is_disabled_by_default_and_read_is_independent() -> None:
    settings = Settings(_env_file=None)
    assert settings.garmin_read_enabled is True
    assert settings.garmin_write_enabled is False
    assert settings.garmin_write_mode == "disabled"


def test_enabled_write_requires_explicit_mode() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, garmin_write_enabled=True)


def test_fake_write_is_forbidden_in_production() -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            environment="production",
            pwa_base_url="https://swim.example.test",
            garmin_write_enabled=True,
            garmin_write_mode="fake",
        )


def test_live_write_requires_encrypted_credentials() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, garmin_write_enabled=True, garmin_write_mode="live")
    Settings(
        _env_file=None,
        garmin_write_enabled=True,
        garmin_write_mode="live",
        garmin_master_keys=keyring(),
        garmin_active_key_version="v1",
    )
