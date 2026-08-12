import base64

import pytest
from pydantic import ValidationError

from swim_coach.settings import Settings


def test_development_auth_requires_explicit_allowlist() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, dev_auth_enabled=True, auth_allowed_emails="")


def test_development_auth_is_impossible_in_production() -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            environment="production",
            pwa_base_url="https://swim.example.com",
            dev_auth_enabled=True,
            auth_allowed_emails="local-swimmer@example.test",
        )


def test_oidc_requires_issuer_client_and_allowlist() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, oidc_issuer="https://issuer.example.com")
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            oidc_issuer="https://issuer.example.com",
            oidc_client_id="client",
        )

    settings = Settings(
        _env_file=None,
        oidc_issuer="https://issuer.example.com",
        oidc_client_id="client",
        auth_allowed_subjects="auth0|allowed",
    )
    assert settings.oidc_redirect_uri == "http://127.0.0.1:14173/api/v1/auth/callback"


def test_garmin_keyring_requires_32_byte_active_key() -> None:
    encoded = base64.urlsafe_b64encode(b"k" * 32).decode().rstrip("=")
    settings = Settings(
        _env_file=None,
        garmin_master_keys=f"v1:{encoded}",
        garmin_active_key_version="v1",
    )
    assert settings.garmin_keyring == {"v1": b"k" * 32}

    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            garmin_master_keys=f"v1:{encoded}",
            garmin_active_key_version="v2",
        )
