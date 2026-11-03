"""Evidence-based transport classification without credentials or raw response bodies."""

from typing import Literal


def classify_failure(
    *,
    http_status: int,
    layer: Literal["MCP", "OAUTH", "BACKEND", "GARMIN"],
    security_source: str | None = None,
    origin_status: int | None = None,
) -> str:
    if http_status == 403 and security_source == "firewallCustom" and origin_status == 0:
        return "EDGE_FIREWALL_BLOCKED"
    if layer == "OAUTH" and http_status in {401, 403}:
        return "OAUTH_AUTHORIZATION_REQUIRED"
    if layer == "MCP" and http_status == 403:
        return "MCP_PERMISSION_DENIED"
    if layer == "GARMIN":
        return "GARMIN_AUTH_REQUIRED" if http_status in {401, 403} else "GARMIN_UNAVAILABLE"
    if http_status >= 500:
        return "BACKEND_UNAVAILABLE"
    if http_status == 422:
        return "SCHEMA_INVALID"
    return "HTTP_FAILURE_UNCLASSIFIED"
