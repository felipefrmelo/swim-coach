import base64
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from swim_coach.domain.shared.errors import DomainError
from swim_coach.infrastructure.auth import OidcClient


def _base64url(value: int) -> str:
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


@pytest.mark.asyncio
async def test_oidc_client_uses_pkce_and_validates_signed_id_token() -> None:
    issuer = "https://issuer.example/"
    client_id = "swim-coach-pwa"
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_numbers = private_key.public_key().public_numbers()
    observed_verifier: str | None = None
    expected_nonce: str | None = None

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal observed_verifier
        if request.url.path == "/.well-known/openid-configuration":
            return httpx.Response(
                200,
                json={
                    "issuer": issuer,
                    "authorization_endpoint": f"{issuer}authorize",
                    "token_endpoint": f"{issuer}oauth/token",
                    "jwks_uri": f"{issuer}.well-known/jwks.json",
                },
            )
        if request.url.path == "/oauth/token":
            form = parse_qs(request.content.decode("utf-8"))
            observed_verifier = form["code_verifier"][0]
            now = datetime.now(UTC)
            token = jwt.encode(
                {
                    "iss": issuer,
                    "aud": client_id,
                    "sub": "auth0|fixture",
                    "email": "swimmer@example.test",
                    "email_verified": True,
                    "name": "Nadador Fixture",
                    "nonce": expected_nonce,
                    "iat": now,
                    "exp": now + timedelta(minutes=5),
                },
                private_key,
                algorithm="RS256",
                headers={"kid": "fixture-key"},
            )
            return httpx.Response(200, json={"id_token": token, "access_token": "not-persisted"})
        if request.url.path == "/.well-known/jwks.json":
            return httpx.Response(
                200,
                json={
                    "keys": [
                        {
                            "kty": "RSA",
                            "kid": "fixture-key",
                            "use": "sig",
                            "alg": "RS256",
                            "n": _base64url(public_numbers.n),
                            "e": _base64url(public_numbers.e),
                        }
                    ]
                },
            )
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = OidcClient(
            issuer=issuer,
            client_id=client_id,
            client_secret=None,
            http_client=http_client,
        )
        authorization = await client.begin_authorization(
            "https://swim.example/api/v1/auth/callback"
        )
        expected_nonce = authorization.nonce
        query = parse_qs(urlparse(authorization.url).query)
        assert query["code_challenge_method"] == ["S256"]
        assert "code_challenge" in query
        principal = await client.exchange_code(
            code="fixture-code",
            code_verifier=authorization.code_verifier,
            nonce=authorization.nonce,
            redirect_uri="https://swim.example/api/v1/auth/callback",
        )

    assert observed_verifier == authorization.code_verifier
    assert principal.subject == "auth0|fixture"
    assert principal.email == "swimmer@example.test"
    assert "access_token" not in principal.claims_snapshot


@pytest.mark.asyncio
async def test_oidc_discovery_fails_closed_on_issuer_mismatch() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "issuer": "https://attacker.example/",
                "authorization_endpoint": "https://attacker.example/authorize",
                "token_endpoint": "https://attacker.example/token",
                "jwks_uri": "https://attacker.example/jwks",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = OidcClient(
            issuer="https://issuer.example/",
            client_id="client",
            client_secret=None,
            http_client=http_client,
        )
        with pytest.raises(DomainError, match="discovery"):
            await client.metadata()
