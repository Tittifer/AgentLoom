"""Tests for MCP tool schema and trusted-context adaptation."""

from typing import cast

import pytest
from mcp.types import Tool
from pydantic import JsonValue

from agentloom.tools.base import ToolContext, ToolExecutionError, ToolUnavailableError
from agentloom.tools.mcp.adapter import MCPToolAdapter
from agentloom.tools.mcp.client import MCPClientError, MCPToolCallError
from agentloom.tools.mcp.manager import MCPManager


class FakeManager:
    def __init__(self) -> None:
        self.arguments: dict[str, object] | None = None
        self.error: MCPClientError | None = None

    async def call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, object],
    ) -> JsonValue:
        assert server_name == "local"
        assert tool_name == "workspace_read"
        self.arguments = arguments
        if self.error is not None:
            raise self.error
        return {"ok": True}


def create_adapter(manager: FakeManager) -> MCPToolAdapter:
    return MCPToolAdapter(
        cast(MCPManager, manager),
        "local",
        Tool(
            name="workspace_read",
            description="Read a file",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "workspace_root": {"type": "string"},
                },
                "required": ["path", "workspace_root"],
            },
        ),
    )


async def test_adapter_hides_and_injects_trusted_context() -> None:
    manager = FakeManager()
    adapter = create_adapter(manager)

    properties = adapter.definition.parameters["properties"]
    assert isinstance(properties, dict)
    assert "workspace_root" not in properties
    assert adapter.definition.parameters["required"] == ["path"]
    result = await adapter.execute(
        {"path": "notes.txt", "workspace_root": "C:/spoofed"},
        ToolContext(
            task_context={},
            upstream_outputs={},
            workspace_root="D:/safe/session",
        ),
    )

    assert result == {"ok": True}
    assert manager.arguments == {
        "path": "notes.txt",
        "workspace_root": "D:/safe/session",
    }


async def test_adapter_requires_context_and_maps_mcp_errors() -> None:
    manager = FakeManager()
    adapter = create_adapter(manager)

    with pytest.raises(ToolUnavailableError, match="workspace_root"):
        await adapter.execute(
            {"path": "notes.txt"},
            ToolContext(task_context={}, upstream_outputs={}),
        )

    context = ToolContext(
        task_context={},
        upstream_outputs={},
        workspace_root="D:/safe/session",
    )
    manager.error = MCPToolCallError("server rejected call")
    with pytest.raises(ToolExecutionError, match="server rejected"):
        await adapter.execute({"path": "notes.txt"}, context)

    manager.error = MCPClientError("transport closed")
    with pytest.raises(ToolUnavailableError, match="transport closed"):
        await adapter.execute({"path": "notes.txt"}, context)


def test_adapter_handles_minimal_tool_schema() -> None:
    adapter = MCPToolAdapter(
        cast(MCPManager, FakeManager()),
        "local",
        Tool(name="workspace_read", inputSchema={"type": "object"}),
    )
    assert adapter.definition.description == "Call the workspace_read MCP tool."
