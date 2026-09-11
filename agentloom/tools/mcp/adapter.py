"""Adapt dynamically discovered MCP tools to AgentLoom's tool contract."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import TYPE_CHECKING

from mcp.types import Tool
from pydantic import JsonValue, TypeAdapter

from agentloom.llm.base import ToolDefinition
from agentloom.tools.base import ToolContext, ToolExecutionError, ToolUnavailableError
from agentloom.tools.mcp.client import MCPClientError, MCPToolCallError

if TYPE_CHECKING:
    from agentloom.tools.mcp.manager import MCPManager

TRUSTED_CONTEXT_PARAMETERS = frozenset(
    {
        "workspace_root",
        "session_id",
        "colony_id",
        "queen_id",
        "actor_type",
        "worker_id",
    }
)
JSON_OBJECT = TypeAdapter(dict[str, JsonValue])


class MCPToolAdapter:
    """Expose one MCP tool while keeping trusted context out of the LLM schema."""

    def __init__(self, manager: MCPManager, server_name: str, tool: Tool) -> None:
        self._manager = manager
        self._server_name = server_name
        schema = deepcopy(JSON_OBJECT.validate_python(tool.inputSchema))
        raw_properties = schema.get("properties")
        properties: dict[str, JsonValue] | None = (
            raw_properties if isinstance(raw_properties, dict) else None
        )
        property_names: set[str] = set(properties.keys()) if properties is not None else set()
        self._context_parameters = TRUSTED_CONTEXT_PARAMETERS & property_names
        if properties is not None:
            for name in self._context_parameters:
                properties.pop(name, None)
        required = schema.get("required")
        if isinstance(required, list):
            schema["required"] = [
                name
                for name in required
                if isinstance(name, str) and name not in self._context_parameters
            ]
        self.definition = ToolDefinition(
            name=tool.name,
            description=tool.description or f"Call the {tool.name} MCP tool.",
            parameters=schema,
        )

    async def execute(
        self,
        arguments: Mapping[str, JsonValue],
        context: ToolContext,
    ) -> JsonValue:
        trusted = {
            "workspace_root": context.workspace_root,
            "session_id": context.session_id,
            "colony_id": context.colony_id,
            "queen_id": context.queen_id,
            "actor_type": context.actor_type,
            "worker_id": context.worker_id,
        }
        missing = [name for name in self._context_parameters if trusted[name] is None]
        if missing:
            raise ToolUnavailableError(
                f"Tool {self.definition.name} requires unavailable runtime context: "
                + ", ".join(sorted(missing))
            )
        clean_arguments = {
            name: value
            for name, value in arguments.items()
            if name not in TRUSTED_CONTEXT_PARAMETERS
        }
        clean_arguments.update(
            {name: trusted[name] for name in self._context_parameters if trusted[name] is not None}
        )
        try:
            return await self._manager.call_tool(
                self._server_name,
                self.definition.name,
                clean_arguments,
            )
        except MCPToolCallError as error:
            raise ToolExecutionError(f"Tool {self.definition.name} failed: {error}") from error
        except MCPClientError as error:
            raise ToolUnavailableError(
                f"Tool server {self._server_name} is unavailable: {error}"
            ) from error


__all__ = ["MCPToolAdapter", "TRUSTED_CONTEXT_PARAMETERS"]
