"""OAuth resource-server token verification for the remote MCP endpoint."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, cast

import httpx
import jwt
from mcp.server.auth.provider import AccessToken, TokenVerifier

LOGGER = logging.getLogger("swim_coach.mcp.auth")


class McpJwtVerifier(TokenVerifier):
    """Validate short-lived JWT access tokens against OIDC discovery and JWKS."""

    def __init__(
        self,
        *,
        issuer: str,
        resource: str,
        http_client: httpx.AsyncClient | None = None,
        cache_ttl_seconds: int = 300,
    ) -> None:
        self._issuer = issuer.rstrip("/")
        self._resource = resource.rstrip("/")
        self._provided_client = http_client
        self._cache_ttl_seconds = cache_ttl_seconds
        self._cached_until = 0.0
        self._metadata: dict[str, Any] | None = None
        self._jwks: dict[str, Any] | None = None
        self._lock = asyncio.Lock()

    async def verify_token(self, token: str) -> AccessToken | None:
        """Return a minimized access context; never log or persist bearer material."""

        try:
            header = jwt.get_unverified_header(token)
            algorithm = header.get("alg")
            key_id = header.get("kid")
            token_type = header.get("typ")
            if algorithm != "RS256" or not isinstance(key_id, str):
                raise jwt.InvalidTokenError("unsupported signing header")
            if token_type is not None and str(token_type).casefold() not in {"jwt", "at+jwt"}:
                raise jwt.InvalidTokenError("unsupported token type")
            metadata, jwks = await self._configuration()
            key = self._find_key(jwks, key_id)
            if key is None:
                metadata, jwks = await self._configuration(force=True)
                key = self._find_key(jwks, key_id)
            if key is None:
                raise jwt.InvalidKeyError("signing key was not found")
            claims = jwt.decode(
                token,
                key=key,
                algorithms=["RS256"],
                audience=self._resource,
                issuer=str(metadata["issuer"]),
                leeway=30,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
            subject = claims.get("sub")
            if not isinstance(subject, str) or not subject.strip():
                raise jwt.InvalidTokenError("subject is missing")
            scopes = self._scopes(claims)
            client_id = claims.get("azp") or claims.get("client_id") or "oauth-client"
            return AccessToken(
                token="",
                client_id=str(client_id),
                scopes=scopes,
                expires_at=int(claims["exp"]),
                resource=self._resource,
                subject=subject,
                claims={
                    "iss": str(claims["iss"]),
                    "aud": claims["aud"],
                    "sub": subject,
                    "scope": " ".join(scopes),
                },
            )
        except (httpx.HTTPError, KeyError, TypeError, ValueError, jwt.PyJWTError) as exc:
            LOGGER.warning("mcp_auth_failed reason=%s", type(exc).__name__)
            return None

    async def _configuration(self, *, force: bool = False) -> tuple[dict[str, Any], dict[str, Any]]:
        now = time.monotonic()
        if not force and self._metadata is not None and self._jwks is not None:
            if now < self._cached_until:
                return self._metadata, self._jwks
        async with self._lock:
            now = time.monotonic()
            if not force and self._metadata is not None and self._jwks is not None:
                if now < self._cached_until:
                    return self._metadata, self._jwks
            client = self._provided_client or httpx.AsyncClient(
                timeout=httpx.Timeout(10.0), follow_redirects=False
            )
            close_client = self._provided_client is None
            try:
                response = await client.get(f"{self._issuer}/.well-known/openid-configuration")
                response.raise_for_status()
                metadata = cast(dict[str, Any], response.json())
                discovered_issuer = str(metadata.get("issuer", ""))
                jwks_uri = str(metadata.get("jwks_uri", ""))
                if discovered_issuer.rstrip("/") != self._issuer or not jwks_uri.startswith(
                    "https://"
                ):
                    raise ValueError("OIDC discovery does not match the configured issuer")
                response = await client.get(jwks_uri)
                response.raise_for_status()
                jwks = cast(dict[str, Any], response.json())
                if not isinstance(jwks.get("keys"), list):
                    raise ValueError("JWKS keys are missing")
            finally:
                if close_client:
                    await client.aclose()
            self._metadata = metadata
            self._jwks = jwks
            self._cached_until = time.monotonic() + self._cache_ttl_seconds
            return metadata, jwks

    @staticmethod
    def _find_key(jwks: dict[str, Any], key_id: str) -> Any | None:
        for item in jwks.get("keys", []):
            if isinstance(item, dict) and item.get("kid") == key_id:
                return jwt.PyJWK.from_dict(item, algorithm="RS256").key
        return None

    @staticmethod
    def _scopes(claims: dict[str, Any]) -> list[str]:
        raw_scope = claims.get("scope")
        scopes = raw_scope.split() if isinstance(raw_scope, str) else []
        permissions = claims.get("permissions")
        if isinstance(permissions, list):
            scopes.extend(item for item in permissions if isinstance(item, str))
        return sorted(set(scopes))
