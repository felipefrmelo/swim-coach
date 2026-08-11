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
