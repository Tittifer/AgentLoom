"""Tests for read-only tool authorization and execution limits."""

import asyncio
from collections.abc import Mapping

import pytest
from pydantic import JsonValue

from agentloom.llm.base import ToolDefinition
from agentloom.tools.base import (
    ToolContext,
    ToolNotAllowedError,
    ToolTimeoutError,
)
from agentloom.tools.builtin.context import ReadTaskContextTool
from agentloom.tools.builtin.mock_search import MockWebSearchTool
from agentloom.tools.registry import ToolRegistry


class SlowTool:
    definition = ToolDefinition(
        name="slow",
        description="Wait too long",
        parameters={"type": "object"},
    )

    async def execute(
        self,
        arguments: Mapping[str, JsonValue],
        context: ToolContext,
    ) -> JsonValue:
        del arguments, context
        await asyncio.sleep(1)
        return {"done": True}


class LargeTool:
    definition = ToolDefinition(
        name="large",
        description="Return a large result",
        parameters={"type": "object"},
    )

    async def execute(
        self,
        arguments: Mapping[str, JsonValue],
        context: ToolContext,
    ) -> JsonValue:
        del arguments, context
        return {"content": "x" * 100}


def context() -> ToolContext:
    return ToolContext(
        task_context={"language": "en"},
        upstream_outputs={"research": {"summary": "facts"}},
    )


async def test_registry_executes_only_allowed_tools() -> None:
    registry = ToolRegistry([ReadTaskContextTool(), MockWebSearchTool()])

    assert await registry.execute("read_task_context", {}, {"read_task_context"}, context()) == {
        "language": "en"
    }
    search = await registry.execute(
        "web_search",
        {"query": "AgentLoom"},
        {"web_search"},
        context(),
    )
    assert isinstance(search, dict)
    assert search["query"] == "AgentLoom"

    with pytest.raises(ToolNotAllowedError):
        await registry.execute("read_task_context", {}, set(), context())


async def test_registry_applies_timeout_and_result_size_limits() -> None:
    registry = ToolRegistry([SlowTool(), LargeTool()], timeout_seconds=0.01, max_result_chars=20)

    with pytest.raises(ToolTimeoutError):
        await registry.execute("slow", {}, {"slow"}, context())
    result = await registry.execute("large", {}, {"large"}, context())
    assert isinstance(result, dict)
    assert result["truncated"] is True


def test_registry_rejects_duplicate_names_and_filters_definitions() -> None:
    registry = ToolRegistry([ReadTaskContextTool()])

    with pytest.raises(ValueError, match="already registered"):
        registry.register(ReadTaskContextTool())
    assert [item.name for item in registry.definitions({"read_task_context", "missing"})] == [
        "read_task_context"
    ]
