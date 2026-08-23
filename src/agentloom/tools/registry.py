"""Static whitelist registry for bounded read-only tools."""

import asyncio
import json
from collections.abc import Collection, Mapping, Sequence

from pydantic import JsonValue, ValidationError

from agentloom.llm.base import ToolDefinition
from agentloom.tools.base import (
    ReadOnlyTool,
    ToolArgumentsError,
    ToolContext,
    ToolNotAllowedError,
    ToolNotFoundError,
    ToolTimeoutError,
)
from agentloom.tools.builtin.context import QueryPreviousNodeResultTool, ReadTaskContextTool
from agentloom.tools.builtin.mock_search import MockWebSearchTool


class ToolRegistry:
    """Validate authorization, timeout, and output size around registered tools."""

    def __init__(
        self,
        tools: Sequence[ReadOnlyTool] = (),
        *,
        timeout_seconds: float = 10,
        max_result_chars: int = 20_000,
    ) -> None:
        self._tools: dict[str, ReadOnlyTool] = {}
        self._timeout_seconds = timeout_seconds
        self._max_result_chars = max_result_chars
        for tool in tools:
            self.register(tool)

    def register(self, tool: ReadOnlyTool) -> None:
        """Register one unique statically constructed tool."""

        name = tool.definition.name
        if name in self._tools:
            raise ValueError(f"Tool {name} is already registered")
        self._tools[name] = tool

    def definitions(self, allowed_tools: Collection[str]) -> list[ToolDefinition]:
        """Return definitions for registered tools in the node whitelist."""

        allowed = set(allowed_tools)
        return [tool.definition for name, tool in self._tools.items() if name in allowed]

    async def execute(
        self,
        name: str,
        arguments: Mapping[str, JsonValue],
        allowed_tools: Collection[str],
        context: ToolContext,
    ) -> JsonValue:
        """Execute one authorized tool and bound its result size."""

        if name not in allowed_tools:
            raise ToolNotAllowedError(f"Tool {name} is not allowed for this node")
        tool = self._tools.get(name)
        if tool is None:
            raise ToolNotFoundError(f"Tool {name} is not registered")
        try:
            result = await asyncio.wait_for(
                tool.execute(arguments, context),
                timeout=self._timeout_seconds,
            )
        except ValidationError as error:
            raise ToolArgumentsError(f"Invalid arguments for {name}: {error}") from error
        except TimeoutError as error:
            raise ToolTimeoutError(f"Tool {name} timed out") from error
        return _limit_result(result, self._max_result_chars)


def _limit_result(result: JsonValue, maximum: int) -> JsonValue:
    serialized = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    if len(serialized) <= maximum:
        return result
    return {
        "truncated": True,
        "content": serialized[:maximum],
    }


def create_builtin_tool_registry() -> ToolRegistry:
    """Create the complete MVP registry without write or command tools."""

    return ToolRegistry(
        [
            ReadTaskContextTool(),
            QueryPreviousNodeResultTool(),
            MockWebSearchTool(),
        ]
    )


__all__ = ["ToolRegistry", "create_builtin_tool_registry"]
