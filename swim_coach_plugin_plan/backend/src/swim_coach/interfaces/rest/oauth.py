"""OAuth protected-resource discovery for the remote MCP endpoint."""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict

from swim_coach.application.services.mcp_read import MCP_READ_SCOPES
from swim_coach.application.services.mcp_write import MCP_WRITE_SCOPES
from swim_coach.settings import get_settings

router = APIRouter(tags=["oauth"])


class ProtectedResourceMetadata(BaseModel):
    """Public RFC 9728 metadata required by OAuth-aware MCP clients."""

    model_config = ConfigDict(extra="forbid")

    resource: str
    authorization_servers: list[str]
    scopes_supported: list[str]


@router.get(
    "/.well-known/oauth-protected-resource",
    response_model=ProtectedResourceMetadata,
)
@router.get(
    "/.well-known/oauth-protected-resource/mcp",
    response_model=ProtectedResourceMetadata,
)
async def protected_resource_metadata() -> ProtectedResourceMetadata:
    """Advertise the configured resource and authorization server without secrets."""

    settings = get_settings()
    if settings.oauth_issuer is None or settings.oauth_resource is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    return ProtectedResourceMetadata(
        resource=str(settings.oauth_resource).rstrip("/"),
        authorization_servers=[str(settings.oauth_issuer).rstrip("/")],
        scopes_supported=list(
            (*MCP_READ_SCOPES, *MCP_WRITE_SCOPES) if settings.mcp_write_enabled else MCP_READ_SCOPES
        ),
    )
