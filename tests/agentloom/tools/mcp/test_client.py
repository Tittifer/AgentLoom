"""Unit tests for MCP response decoding and lifecycle guards."""

from contextlib import AsyncExitStack
from typing import Any, cast

import pytest
from mcp.types import CallToolResult, TextContent

from agentloom.tools.mcp.client import (
    MCPClient,
    MCPClientError,
    MCPServerConfig,
    MCPToolCallError,
)


class FakeSession:
    def __init__(self, result: CallToolResult | Exception) -> None:
        self.result = result

    async def call_tool(self, *args: Any, **kwargs: Any) -> CallToolResult:
        del args, kwargs
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def client_with(result: CallToolResult | Exception) -> MCPClient:
    client = MCPClient(MCPServerConfig(name="test", command="python"))
    client._session = cast(Any, FakeSession(result))  # pyright: ignore[reportPrivateUsage]
    return client


async def test_client_requires_connection_and_wraps_transport_errors() -> None:
    client = MCPClient(MCPServerConfig(name="test", command="python"))
    with pytest.raises(MCPClientError, match="not connected"):
        await client.call_tool("example", {})

    client = client_with(RuntimeError("closed"))
    with pytest.raises(MCPClientError, match="closed"):
        await client.call_tool("example", {})


async def test_client_decodes_structured_json_text_and_plain_text() -> None:
    structured = client_with(CallToolResult(content=[], structuredContent={"ok": True}))
    assert await structured.call_tool("example", {}) == {"ok": True}

    json_text = client_with(CallToolResult(content=[TextContent(type="text", text='{"value": 2}')]))
    assert await json_text.call_tool("example", {}) == {"value": 2}

    plain_text = client_with(
        CallToolResult(content=[TextContent(type="text", text="plain result")])
    )
    assert await plain_text.call_tool("example", {}) == "plain result"

    empty = client_with(CallToolResult(content=[]))
    assert await empty.call_tool("example", {}) is None


async def test_client_reports_mcp_tool_errors() -> None:
    client = client_with(
        CallToolResult(
            content=[TextContent(type="text", text="invalid request")],
            isError=True,
        )
    )
    with pytest.raises(MCPToolCallError, match="invalid request"):
        await client.call_tool("example", {})

    client = client_with(CallToolResult(content=[], isError=True))
    with pytest.raises(MCPToolCallError, match="MCP tool example failed"):
        await client.call_tool("example", {})


async def test_client_close_clears_state() -> None:
    client = client_with(CallToolResult(content=[]))
    client._stack = AsyncExitStack()  # pyright: ignore[reportPrivateUsage]
    await client.close()
    assert client.tools == ()
    await client.close()
