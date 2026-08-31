"""Deterministic language-model providers for tests and local development."""

import asyncio
from collections.abc import AsyncIterator, Sequence
from copy import deepcopy

from pydantic import JsonValue

from agentloom.llm.base import LLMProviderError, LLMRequest, LLMResponse, LLMStreamChunk

ScriptedResult = LLMResponse | Exception


class ScriptedMockLLMProvider:
    """Return a preconfigured response or exception for each call in order."""

    def __init__(self, results: Sequence[ScriptedResult]) -> None:
        self._results = tuple(results)
        self._index = 0
        self._lock = asyncio.Lock()
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Record the request and consume exactly one scripted result."""

        async with self._lock:
            self.requests.append(request.model_copy(deep=True))
            if self._index >= len(self._results):
                raise LLMProviderError("Scripted mock response sequence is exhausted")
            result = self._results[self._index]
            self._index += 1

        if isinstance(result, Exception):
            raise result
        return result.model_copy(deep=True)

    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMStreamChunk]:
        """Expose scripted results through the same stream contract as real providers."""

        response = await self.complete(request)
        if response.content:
            yield LLMStreamChunk(content_delta=response.content)
        yield LLMStreamChunk(
            tool_calls_started=bool(response.tool_calls),
            response=response,
        )


class SchemaMockLLMProvider:
    """Generate a deterministic value that satisfies common JSON Schema shapes."""

    def __init__(self, model: str = "mock/schema") -> None:
        self._model = model
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Create a schema-shaped response without external network access."""

        self.requests.append(request.model_copy(deep=True))
        structured_output = (
            _mock_object(request.response_schema) if request.response_schema is not None else None
        )
        return LLMResponse(
            content=None if structured_output is not None else "模拟 Queen 已收到消息。",
            structured_output=structured_output,
            input_tokens=10,
            output_tokens=5,
            model=self._model,
        )

    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMStreamChunk]:
        """Expose deterministic output through the provider stream contract."""

        response = await self.complete(request)
        if response.content:
            yield LLMStreamChunk(content_delta=response.content)
        yield LLMStreamChunk(response=response)


def _mock_object(schema: dict[str, JsonValue]) -> dict[str, JsonValue]:
    value = _mock_value(schema, "result")
    if not isinstance(value, dict):
        raise LLMProviderError("Worker response schema must describe a JSON object")
    return value


def _mock_value(schema: dict[str, JsonValue], name: str) -> JsonValue:
    if "const" in schema:
        return deepcopy(schema["const"])
    examples = schema.get("examples")
    if isinstance(examples, list) and examples:
        return deepcopy(examples[0])
    enum_values = schema.get("enum")
    if isinstance(enum_values, list) and enum_values:
        return deepcopy(enum_values[0])
    if "default" in schema:
        return deepcopy(schema["default"])

    schema_type = schema.get("type")
    if isinstance(schema_type, list):
        schema_type = next((item for item in schema_type if item != "null"), "null")
    if schema_type == "object" or isinstance(schema.get("properties"), dict):
        properties = schema.get("properties")
        if not isinstance(properties, dict):
            return {}
        result: dict[str, JsonValue] = {}
        for property_name, property_schema in properties.items():
            if isinstance(property_schema, dict):
                result[property_name] = _mock_value(property_schema, property_name)
        return result
    if schema_type == "array":
        minimum = schema.get("minItems")
        count = int(minimum) if isinstance(minimum, int) else 1
        item_schema = schema.get("items")
        if not isinstance(item_schema, dict):
            return []
        return [_mock_value(item_schema, name) for _ in range(count)]
    if schema_type == "integer":
        minimum = schema.get("minimum")
        return int(minimum) if isinstance(minimum, (int, float)) else 0
    if schema_type == "number":
        minimum = schema.get("minimum")
        return float(minimum) if isinstance(minimum, (int, float)) else 0.0
    if schema_type == "boolean":
        return True
    if schema_type == "null":
        return None

    minimum_length = schema.get("minLength")
    value = f"Mock {name.replace('_', ' ')}"
    if isinstance(minimum_length, int) and len(value) < minimum_length:
        value += "x" * (minimum_length - len(value))
    return value


__all__ = ["SchemaMockLLMProvider", "ScriptedMockLLMProvider", "ScriptedResult"]
