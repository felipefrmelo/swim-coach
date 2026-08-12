"""Validate public OAuth/MCP metadata without obtaining or printing tokens."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx


class ProbeError(RuntimeError):
    """A sanitized, actionable metadata validation failure."""


def require_https(value: str, label: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ProbeError(f"{label} must be an absolute HTTPS URL")
    return value.rstrip("/")


def require_resource_url(value: str, label: str, *, allow_loopback_http: bool) -> str:
    """Require HTTPS, except explicit loopback HTTP used behind a dev tunnel."""

    parsed = urlparse(value)
    if parsed.scheme == "https" and parsed.netloc:
        return value.rstrip("/")
    loopback_hosts = {"127.0.0.1", "localhost", "::1"}
    if (
        allow_loopback_http
        and parsed.scheme == "http"
        and parsed.netloc
        and parsed.hostname in loopback_hosts
    ):
        return value.rstrip("/")
    raise ProbeError(
        f"{label} must be an absolute HTTPS URL"
        + (" or an HTTP loopback URL" if allow_loopback_http else "")
    )


def fetch_json(client: httpx.Client, url: str) -> dict[str, Any]:
    response = client.get(url)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ProbeError(f"metadata at {url} is not a JSON object")
    return payload


def validate_authorization_server(metadata: dict[str, Any]) -> dict[str, Any]:
    authorization_endpoint = metadata.get("authorization_endpoint")
    token_endpoint = metadata.get("token_endpoint")
    if not isinstance(authorization_endpoint, str) or not isinstance(token_endpoint, str):
        raise ProbeError("authorization server metadata lacks required endpoints")
    require_https(authorization_endpoint, "authorization_endpoint")
    require_https(token_endpoint, "token_endpoint")

    code_methods = metadata.get("code_challenge_methods_supported", [])
    if "S256" not in code_methods:
        raise ProbeError("authorization server metadata does not advertise PKCE S256")

    response_types = metadata.get("response_types_supported", [])
    if "code" not in response_types:
        raise ProbeError("authorization server metadata does not advertise response_type=code")

    registration_endpoint = metadata.get("registration_endpoint")
    cimd_supported = metadata.get("client_id_metadata_document_supported") is True
    if not isinstance(registration_endpoint, str) and not cimd_supported:
        raise ProbeError("metadata advertises neither DCR nor CIMD client registration")
    if isinstance(registration_endpoint, str):
        require_https(registration_endpoint, "registration_endpoint")

    return {
        "authorization_code": True,
        "pkce_s256": True,
        "dcr": isinstance(registration_endpoint, str),
        "cimd": cimd_supported,
        "token_endpoint_auth_methods": metadata.get("token_endpoint_auth_methods_supported", []),
    }


def validate_protected_resource(
    metadata: dict[str, Any], expected_resource: str, expected_issuer: str
) -> dict[str, Any]:
    if metadata.get("resource") != expected_resource:
        raise ProbeError("protected resource metadata has an unexpected resource identifier")
    authorization_servers = metadata.get("authorization_servers", [])
    if expected_issuer not in authorization_servers:
        raise ProbeError("protected resource metadata does not reference the expected issuer")
    scopes = metadata.get("scopes_supported", [])
    if not isinstance(scopes, list) or not all(isinstance(scope, str) for scope in scopes):
        raise ProbeError("protected resource scopes_supported must be a string array")
    return {"resource_binding": True, "scope_count": len(scopes)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--issuer", required=True, help="Public OAuth/OIDC issuer URL")
    parser.add_argument(
        "--resource",
        help="Canonical MCP resource identifier; required with --resource-metadata-url",
    )
    parser.add_argument(
        "--resource-metadata-url",
        help="Public RFC 9728 protected resource metadata URL",
    )
    parser.add_argument(
        "--allow-loopback-http",
        action="store_true",
        help="Allow HTTP only on loopback for Secure MCP Tunnel development",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        issuer = require_https(args.issuer, "issuer")
        if bool(args.resource) != bool(args.resource_metadata_url):
            raise ProbeError("--resource and --resource-metadata-url must be provided together")
        with httpx.Client(timeout=10, follow_redirects=False) as client:
            metadata_url = urljoin(f"{issuer}/", ".well-known/openid-configuration")
            auth_metadata = fetch_json(client, metadata_url)
            if auth_metadata.get("issuer", "").rstrip("/") != issuer:
                raise ProbeError("authorization server metadata issuer does not match exactly")
            result: dict[str, Any] = {
                "issuer_metadata": validate_authorization_server(auth_metadata)
            }
            if args.resource and args.resource_metadata_url:
                resource = require_resource_url(
                    args.resource,
                    "resource",
                    allow_loopback_http=args.allow_loopback_http,
                )
                resource_metadata_url = require_resource_url(
                    args.resource_metadata_url,
                    "resource_metadata_url",
                    allow_loopback_http=args.allow_loopback_http,
                )
                resource_metadata = fetch_json(client, resource_metadata_url)
                result["protected_resource_metadata"] = validate_protected_resource(
                    resource_metadata, resource, issuer
                )
    except (ProbeError, httpx.HTTPError, json.JSONDecodeError) as exc:
        print(f"oauth_probe=failed reason={exc}", file=sys.stderr)
        return 1

    print(json.dumps({"oauth_probe": "passed", **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
