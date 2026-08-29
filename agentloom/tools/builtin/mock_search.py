"""Deterministic read-only search tool for local development and tests."""

from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from agentloom.llm.base import ToolDefinition
from agentloom.tools.base import ToolContext


class SearchArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    query: str = Field(min_length=1, max_length=500)


class MockWebSearchTool:
    definition = ToolDefinition(
        name="web_search",
        description="Return a deterministic local search result without network access.",
        parameters={
            "type": "object",
            "required": ["query"],
            "properties": {"query": {"type": "string", "minLength": 1, "maxLength": 500}},
            "additionalProperties": False,
        },
    )

    async def execute(
        self,
        arguments: Mapping[str, JsonValue],
        context: ToolContext,
    ) -> JsonValue:
        del context
        parsed = SearchArguments.model_validate(arguments)
        return {
            "query": parsed.query,
            "results": [
                {
                    "title": f"Mock result for {parsed.query}",
                    "url": "https://example.invalid/mock-search",
                }
            ],
        }


__all__ = ["MockWebSearchTool"]
