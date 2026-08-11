import importlib.util
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).parents[2] / "scripts" / "probe_oauth_metadata.py"
SPEC = importlib.util.spec_from_file_location("probe_oauth_metadata", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


def valid_metadata() -> dict[str, Any]:
    return {
        "authorization_endpoint": "https://auth.example.test/authorize",
        "token_endpoint": "https://auth.example.test/oauth/token",
        "registration_endpoint": "https://auth.example.test/oidc/register",
        "code_challenge_methods_supported": ["S256"],
        "response_types_supported": ["code"],
        "token_endpoint_auth_methods_supported": ["none"],
    }


def test_oauth_probe_accepts_pkce_and_dcr() -> None:
    assert probe.validate_authorization_server(valid_metadata()) == {
        "authorization_code": True,
        "pkce_s256": True,
        "dcr": True,
        "cimd": False,
        "token_endpoint_auth_methods": ["none"],
    }


def test_oauth_probe_rejects_missing_s256() -> None:
    metadata = valid_metadata()
    metadata["code_challenge_methods_supported"] = ["plain"]

    with pytest.raises(probe.ProbeError, match="PKCE S256"):
        probe.validate_authorization_server(metadata)


def test_protected_resource_requires_exact_binding() -> None:
    with pytest.raises(probe.ProbeError, match="unexpected resource"):
        probe.validate_protected_resource(
            {
                "resource": "https://other.example.test",
                "authorization_servers": ["https://auth.example.test"],
                "scopes_supported": [],
            },
            "https://mcp.example.test",
            "https://auth.example.test",
        )
