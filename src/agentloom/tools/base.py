"""Contracts and errors shared by read-only worker tools."""

from collections.abc import Mapping
from typing import Protocol

from pydantic import BaseModel, ConfigDict, JsonValue

from agentloom.llm.base import ToolDefinition


class ToolContext(BaseModel):
    """Read-only data available to built-in tools for one node attempt."""

    model_config = ConfigDict(extra="forbid")

    task_context: dict[str, JsonValue]
    upstream_outputs: dict[str, dict[str, JsonValue]]


class ReadOnlyTool(Protocol):
    """One statically registered tool with validated arguments."""

    definition: ToolDefinition

    async def execute(
        self,
        arguments: Mapping[str, JsonValue],
        context: ToolContext,
    ) -> JsonValue: ...


class ToolError(RuntimeError):
    """Base error returned to the model for a rejected tool call."""

    code = "TOOL_ERROR"

    def as_payload(self) -> dict[str, JsonValue]:
        return {"error": {"code": self.code, "message": str(self)}}


class ToolNotAllowedError(ToolError):
    code = "TOOL_NOT_ALLOWED"


class ToolNotFoundError(ToolError):
    code = "TOOL_NOT_FOUND"


class ToolArgumentsError(ToolError):
    code = "TOOL_ARGUMENTS_INVALID"


class ToolTimeoutError(ToolError):
    code = "TOOL_TIMEOUT"


__all__ = [
    "ReadOnlyTool",
    "ToolArgumentsError",
    "ToolContext",
    "ToolError",
    "ToolNotAllowedError",
    "ToolNotFoundError",
    "ToolTimeoutError",
]
