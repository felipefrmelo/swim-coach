"""Harmless P00 MCP server."""

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations

from swim_coach.application.queries.get_capabilities import (
    CapabilityResult,
)
from swim_coach.application.queries.get_capabilities import (
    get_capabilities as query_capabilities,
)


def create_mcp_server(
    *, allowed_hosts: list[str] | None = None, allowed_origins: list[str] | None = None
) -> FastMCP:
    """Create a server whose session manager has an independent lifecycle."""

    server = FastMCP(
        name="swim-coach",
        instructions=(
            "P00 exposes one harmless public capability check. Do not infer private-data, "
            "OAuth, Garmin, write, or production readiness from this server."
        ),
        streamable_http_path="/",
        json_response=True,
        stateless_http=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=allowed_hosts or ["127.0.0.1", "127.0.0.1:*", "localhost", "localhost:*"],
            allowed_origins=allowed_origins or ["http://127.0.0.1:*", "http://localhost:*"],
        ),
    )

    @server.tool(
        name="get_capabilities",
        title="Get Swim Coach capabilities",
        description=(
            "Return the harmless capabilities and explicit limitations enabled in the P00 spike."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
        structured_output=True,
    )
    def get_capabilities() -> CapabilityResult:
        """Return the current public release capability envelope."""

        return query_capabilities()

    return server
