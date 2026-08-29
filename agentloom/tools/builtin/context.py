"""Read-only tools backed by the current node execution context."""

from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, JsonValue

from agentloom.llm.base import ToolDefinition
from agentloom.tools.base import ToolArgumentsError, ToolContext


class NoArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PreviousResultArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    node_key: str


class ReadTaskContextTool:
    definition = ToolDefinition(
        name="read_task_context",
        description="Read the immutable JSON context supplied with the current task.",
        parameters={"type": "object", "additionalProperties": False},
    )

    async def execute(
        self,
        arguments: Mapping[str, JsonValue],
        context: ToolContext,
    ) -> JsonValue:
        NoArguments.model_validate(arguments)
        return context.task_context


class QueryPreviousNodeResultTool:
    definition = ToolDefinition(
        name="query_previous_node_result",
        description="Read the completed result of one direct upstream workflow node.",
        parameters={
            "type": "object",
            "required": ["node_key"],
            "properties": {"node_key": {"type": "string"}},
            "additionalProperties": False,
        },
    )

    async def execute(
        self,
        arguments: Mapping[str, JsonValue],
        context: ToolContext,
    ) -> JsonValue:
        parsed = PreviousResultArguments.model_validate(arguments)
        result = context.upstream_outputs.get(parsed.node_key)
        if result is None:
            raise ToolArgumentsError(
                f"Node {parsed.node_key} is not a completed direct upstream node"
            )
        return result


__all__ = ["QueryPreviousNodeResultTool", "ReadTaskContextTool"]
