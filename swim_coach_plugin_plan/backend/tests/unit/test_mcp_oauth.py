from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest import mock

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from swim_coach.infrastructure.auth import McpJwtVerifier
from swim_coach.infrastructure.auth import mcp as mcp_auth

ISSUER = "https://tenant.example.test"
RESOURCE = "https://swim.example.test/mcp"


def _keys() -> tuple[rsa.RSAPrivateKey, dict[str, object]]:
    private_key = rsa.generate_private_key(public_exponent=65_537, key_size=2048)
    public_numbers = private_key.public_key().public_numbers()
    encode = lambda value: jwt.utils.base64url_encode(  # noqa: E731 - compact JWK fixture
        value.to_bytes((value.bit_length() + 7) // 8, "big")
    ).decode()
    return private_key, {
        "kty": "RSA",
        "kid": "fixture-key",
        "use": "sig",
        "alg": "RS256",
        "n": encode(public_numbers.n),
        "e": encode(public_numbers.e),
    }


def _token(private_key: rsa.RSAPrivateKey, **overrides: object) -> str:
    now = datetime.now(UTC)
    claims: dict[str, object] = {
        "iss": ISSUER,
        "aud": RESOURCE,
        "sub": "athlete-subject",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=5)).timestamp()),
        "scope": "activities:read analytics:read",
        "azp": "chatgpt-fixture",
    }
    claims.update(overrides)
    return jwt.encode(
        claims,
        private_key,
        algorithm="RS256",
        headers={"kid": "fixture-key", "typ": "at+jwt"},
    )


@pytest.mark.asyncio
async def test_mcp_verifier_validates_signature_claims_audience_and_scopes() -> None:
    private_key, jwk = _keys()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/.well-known/openid-configuration":
            return httpx.Response(
                200,
                json={"issuer": ISSUER, "jwks_uri": f"{ISSUER}/.well-known/jwks.json"},
            )
        return httpx.Response(200, json={"keys": [jwk]})

    with mock.patch.object(mcp_auth.LOGGER, "warning") as warning:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            verifier = McpJwtVerifier(issuer=ISSUER, resource=RESOURCE, http_client=client)
            token = _token(private_key)
            verified = await verifier.verify_token(token)
            invalid_audience = await verifier.verify_token(
                _token(private_key, aud="https://other.example.test/mcp")
            )
            expired = await verifier.verify_token(
                _token(
                    private_key,
                    exp=int((datetime.now(UTC) - timedelta(minutes=1)).timestamp()),
                )
            )

    assert verified is not None
    assert verified.token == ""
    assert verified.subject == "athlete-subject"
    assert verified.resource == RESOURCE
    assert verified.scopes == ["activities:read", "analytics:read"]
    assert invalid_audience is None
    assert expired is None
    assert warning.call_count == 2
    assert all(token not in repr(call) for call in warning.call_args_list)


@pytest.mark.asyncio
async def test_mcp_verifier_rejects_discovery_issuer_mismatch() -> None:
    private_key, _ = _keys()

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "issuer": "https://attacker.example.test",
                "jwks_uri": f"{ISSUER}/.well-known/jwks.json",
            },
        )

    with mock.patch.object(mcp_auth.LOGGER, "warning") as warning:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            verifier = McpJwtVerifier(issuer=ISSUER, resource=RESOURCE, http_client=client)
            assert await verifier.verify_token(_token(private_key)) is None

    warning.assert_called_once_with("mcp_auth_failed reason=%s", "ValueError")
