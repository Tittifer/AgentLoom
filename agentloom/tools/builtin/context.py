"""Read-only tools backed by the current node execution context."""

from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, JsonValue

from agentloom.llm.base import ToolDefinition
from agentloom.tools.base import ToolContext


class NoArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReadTaskContextTool:
    definition = ToolDefinition(
        name="read_task_context",
        description="读取当前 Queen 或 Worker 会话的不可变任务上下文。",
        parameters={"type": "object", "additionalProperties": False},
    )

    async def execute(
        self,
        arguments: Mapping[str, JsonValue],
        context: ToolContext,
    ) -> JsonValue:
        NoArguments.model_validate(arguments)
        return context.task_context


__all__ = ["ReadTaskContextTool"]
