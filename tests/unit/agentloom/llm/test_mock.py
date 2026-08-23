"""Tests for deterministic mock LLM providers."""

import asyncio

import pytest
from pydantic import JsonValue

from agentloom.llm.base import LLMMessage, LLMProviderError, LLMRequest, LLMResponse, ToolCall
from agentloom.llm.mock import SchemaMockLLMProvider, ScriptedMockLLMProvider


def request(schema: dict[str, JsonValue] | None = None) -> LLMRequest:
    return LLMRequest(
        model="mock/test",
        messages=[LLMMessage(role="user", content="Work")],
        response_schema=schema,
    )


async def test_scripted_mock_returns_tools_errors_and_outputs_in_order() -> None:
    tool_response = LLMResponse(
        model="mock/test",
        tool_calls=[ToolCall(id="call-1", name="lookup", arguments={"query": "value"})],
    )
    output_response = LLMResponse(
        model="mock/test",
        structured_output={"answer": "done"},
    )
    provider = ScriptedMockLLMProvider(
        [tool_response, LLMProviderError("planned failure"), output_response]
    )

    assert (await provider.complete(request())).tool_calls[0].name == "lookup"
    with pytest.raises(LLMProviderError, match="planned failure"):
        await provider.complete(request())
    assert (await provider.complete(request())).structured_output == {"answer": "done"}
    assert len(provider.requests) == 3

    with pytest.raises(LLMProviderError, match="exhausted"):
        await provider.complete(request())


async def test_scripted_mock_keeps_concurrent_call_order_unique() -> None:
    provider = ScriptedMockLLMProvider(
        [
            LLMResponse(model="mock/test", content="first"),
            LLMResponse(model="mock/test", content="second"),
        ]
    )

    responses = await asyncio.gather(provider.complete(request()), provider.complete(request()))

    assert [response.content for response in responses] == ["first", "second"]


async def test_schema_mock_generates_a_valid_nested_object() -> None:
    provider = SchemaMockLLMProvider()
    schema: dict[str, JsonValue] = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "minLength": 20},
            "items": {
                "type": "array",
                "minItems": 2,
                "items": {"type": "integer", "minimum": 3},
            },
            "active": {"type": "boolean"},
        },
    }

    response = await provider.complete(request(schema))

    assert response.structured_output is not None
    assert len(str(response.structured_output["title"])) >= 20
    assert response.structured_output["items"] == [3, 3]
    assert response.structured_output["active"] is True


async def test_schema_mock_rejects_non_object_response_schema() -> None:
    provider = SchemaMockLLMProvider()

    with pytest.raises(LLMProviderError, match="JSON object"):
        await provider.complete(request({"type": "string"}))
