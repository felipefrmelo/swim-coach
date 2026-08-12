"""Authorization Code + PKCE OIDC client for the PWA BFF."""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass
from typing import Any, cast
from urllib.parse import urlencode

import httpx
import jwt

from swim_coach.domain.shared.errors import DomainError


@dataclass(frozen=True, slots=True)
class OidcAuthorization:
    url: str
    state: str
    code_verifier: str
    nonce: str


@dataclass(frozen=True, slots=True)
class OidcPrincipal:
    subject: str
    email: str
    display_name: str
    claims_snapshot: dict[str, str | bool]


@dataclass(frozen=True, slots=True)
class OidcMetadata:
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str


class OidcClient:
    def __init__(
        self,
        *,
        issuer: str,
        client_id: str,
        client_secret: str | None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._issuer = issuer.rstrip("/")
        self._client_id = client_id
        self._client_secret = client_secret
        self._provided_http_client = http_client

    def _request_client(self) -> httpx.AsyncClient:
        if self._provided_http_client is not None:
            return self._provided_http_client
        return httpx.AsyncClient(timeout=httpx.Timeout(10.0), follow_redirects=False)

    async def metadata(self) -> OidcMetadata:
        client = self._request_client()
        should_close = self._provided_http_client is None
        try:
            response = await client.get(f"{self._issuer}/.well-known/openid-configuration")
            response.raise_for_status()
            payload = cast(dict[str, Any], response.json())
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise DomainError("TOKEN_INVALID", "OIDC discovery failed.") from exc
        finally:
            if should_close:
                await client.aclose()
        raw_issuer = str(payload.get("issuer", ""))
        issuer = raw_issuer.rstrip("/")
        authorization_endpoint = str(payload.get("authorization_endpoint", ""))
        token_endpoint = str(payload.get("token_endpoint", ""))
        jwks_uri = str(payload.get("jwks_uri", ""))
        if issuer != self._issuer or not all(
            value.startswith("https://")
            for value in (authorization_endpoint, token_endpoint, jwks_uri)
        ):
            raise DomainError("TOKEN_INVALID", "OIDC discovery metadata is invalid.")
        return OidcMetadata(raw_issuer, authorization_endpoint, token_endpoint, jwks_uri)

    async def begin_authorization(self, redirect_uri: str) -> OidcAuthorization:
        metadata = await self.metadata()
        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)
        code_verifier = secrets.token_urlsafe(64)
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode("ascii")).digest())
            .rstrip(b"=")
            .decode("ascii")
        )
        query = urlencode(
            {
                "response_type": "code",
                "client_id": self._client_id,
                "redirect_uri": redirect_uri,
                "scope": "openid profile email",
                "state": state,
                "nonce": nonce,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
        return OidcAuthorization(
            url=f"{metadata.authorization_endpoint}?{query}",
            state=state,
            code_verifier=code_verifier,
            nonce=nonce,
        )

    async def exchange_code(
        self,
        *,
        code: str,
        code_verifier: str,
        nonce: str,
        redirect_uri: str,
    ) -> OidcPrincipal:
        metadata = await self.metadata()
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
        }
        auth: tuple[str, str] | None = None
        if self._client_secret:
            auth = (self._client_id, self._client_secret)
        else:
            data["client_id"] = self._client_id
        client = self._request_client()
        should_close = self._provided_http_client is None
        try:
            if auth is None:
                token_response = await client.post(metadata.token_endpoint, data=data)
            else:
                token_response = await client.post(metadata.token_endpoint, data=data, auth=auth)
            token_response.raise_for_status()
            token_payload = cast(dict[str, Any], token_response.json())
            id_token = token_payload.get("id_token")
            if not isinstance(id_token, str):
                raise ValueError("missing id_token")
            claims = await self._validate_id_token(client, metadata, id_token, nonce)
        except (httpx.HTTPError, ValueError, KeyError, jwt.PyJWTError) as exc:
            raise DomainError("TOKEN_INVALID", "OIDC callback could not be validated.") from exc
        finally:
            if should_close:
                await client.aclose()
        subject = claims.get("sub")
        email = claims.get("email")
        email_verified = claims.get("email_verified")
        if not isinstance(subject, str) or not isinstance(email, str) or email_verified is not True:
            raise DomainError("TOKEN_INVALID", "A verified OIDC email is required.")
        name = claims.get("name")
        display_name = name if isinstance(name, str) and name.strip() else email.split("@", 1)[0]
        snapshot: dict[str, str | bool] = {"email_verified": True}
        locale = claims.get("locale")
        if isinstance(locale, str):
            snapshot["locale"] = locale
        return OidcPrincipal(subject, email.casefold(), display_name, snapshot)

    async def _validate_id_token(
        self,
        client: httpx.AsyncClient,
        metadata: OidcMetadata,
        id_token: str,
        nonce: str,
    ) -> dict[str, Any]:
        header = jwt.get_unverified_header(id_token)
        if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
            raise jwt.InvalidAlgorithmError("only RS256 with kid is accepted")
        jwks_response = await client.get(metadata.jwks_uri)
        jwks_response.raise_for_status()
        jwks = cast(dict[str, Any], jwks_response.json())
        keys = jwks.get("keys")
        if not isinstance(keys, list):
            raise jwt.InvalidKeyError("JWKS keys are missing")
        matching_key = next(
            (key for key in keys if isinstance(key, dict) and key.get("kid") == header["kid"]),
            None,
        )
        if matching_key is None:
            raise jwt.InvalidKeyError("signing key was not found")
        key = jwt.PyJWK.from_dict(matching_key, algorithm="RS256").key
        claims = jwt.decode(
            id_token,
            key=key,
            algorithms=["RS256"],
            audience=self._client_id,
            issuer=metadata.issuer,
            leeway=30,
            options={"require": ["exp", "iat", "iss", "aud", "sub", "nonce"]},
        )
        if not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
            raise jwt.InvalidTokenError("nonce mismatch")
        return claims
