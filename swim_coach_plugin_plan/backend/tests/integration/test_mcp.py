import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from swim_coach.bootstrap.api import create_app


@pytest.mark.asyncio
async def test_mcp_lists_and_calls_get_capabilities() -> None:
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            async with streamable_http_client(
                "http://127.0.0.1/mcp/",
                http_client=client,
            ) as (read_stream, write_stream, _):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    listed = await session.list_tools()
                    result = await session.call_tool("get_capabilities", {})

    assert [tool.name for tool in listed.tools] == ["get_capabilities"]
    tool = listed.tools[0]
    assert tool.annotations is not None
    assert tool.annotations.readOnlyHint is True
    assert tool.annotations.destructiveHint is False
    assert tool.annotations.openWorldHint is False
    assert result.isError is False
    assert result.structuredContent is not None
    assert result.structuredContent["status"] == "OK"
    assert result.structuredContent["data"]["available_tools"] == ["get_capabilities"]
