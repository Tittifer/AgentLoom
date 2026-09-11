"""Integration tests for the bundled stdio MCP server."""

from typing import Any, cast

import pytest

from agentloom.tools.base import ToolContext
from agentloom.tools.mcp.client import MCPClientError, MCPServerConfig
from agentloom.tools.mcp.manager import MCPManager, builtin_server_config


async def test_manager_discovers_and_calls_bundled_tools() -> None:
    manager = MCPManager([builtin_server_config()])
    await manager.start()
    try:
        client = next(  # pyright: ignore[reportPrivateUsage]
            iter(manager._clients.values())  # pyright: ignore[reportPrivateUsage]
        )
        await client.connect()
        adapters = {tool.definition.name: tool for tool in manager.tool_adapters()}
        assert {
            "get_current_time",
            "web_fetch",
            "workspace_glob",
            "workspace_read",
            "workspace_search",
        } <= set(adapters)
        result = await adapters["get_current_time"].execute(
            {"timezone": "UTC"},
            ToolContext(task_context={}, upstream_outputs={}),
        )
        assert isinstance(result, dict)
        assert result["timezone"] == "UTC"
    finally:
        await manager.close()


async def test_manager_routes_calls_and_handles_unavailable_server() -> None:
    manager = MCPManager([])
    await manager.start()
    await manager.start()
    assert manager.tool_adapters() == []
    with pytest.raises(MCPClientError, match="not connected"):
        await manager.call_tool("missing", "example", {})
    await manager.close()


async def test_manager_isolates_server_start_and_stop_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BrokenClient:
        def __init__(self, config: MCPServerConfig) -> None:
            self.config = config
            self.tools: tuple[Any, ...] = ()

        async def connect(self) -> None:
            raise RuntimeError("cannot start")

        async def close(self) -> None:
            raise RuntimeError("cannot stop")

    monkeypatch.setattr("agentloom.tools.mcp.manager.MCPClient", BrokenClient)
    manager = MCPManager([MCPServerConfig(name="broken", command="missing")])
    await manager.start()
    assert manager.tool_adapters() == []

    manager._clients["broken"] = cast(  # pyright: ignore[reportPrivateUsage]
        Any,
        BrokenClient(MCPServerConfig(name="broken", command="missing")),
    )
    await manager.close()
