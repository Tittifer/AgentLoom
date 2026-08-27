"""Offline contract tests for the LiteLLM request and response adapter."""

import asyncio

import pytest

from agentloom.llm.base import (
    LLMMessage,
    LLMRequest,
    LLMResponseError,
    LLMTimeoutError,
    ToolDefinition,
)
from agentloom.llm.litellm_provider import LiteLLMProvider


class RecordingCompletion:
    def __init__(self, result: object) -> None:
        self._result = result
        self.parameters: dict[str, object] = {}

    async def __call__(self, **parameters: object) -> object:
        self.parameters = parameters
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


def request(timeout_seconds: float = 1) -> LLMRequest:
    return LLMRequest(
        model="openai/test-model",
        messages=[LLMMessage(role="user", content="Return JSON")],
        tools=[
            ToolDefinition(
                name="lookup",
                description="Look up a value",
                parameters={"type": "object"},
            )
        ],
        response_schema={
            "type": "object",
            "required": ["answer"],
            "properties": {"answer": {"type": "string"}},
        },
        timeout_seconds=timeout_seconds,
    )


async def test_litellm_provider_normalizes_request_response_tools_and_usage() -> None:
    completion = RecordingCompletion(
        {
            "model": "provider/model-version",
            "choices": [
                {
                    "message": {
                        "content": '{"answer":"done"}',
                        "tool_calls": [
                            {
                                "id": "call-1",
                                "function": {
                                    "name": "lookup",
                                    "arguments": '{"query":"value"}',
                                },
                            }
                        ],
                    }
                }
            ],
            "usage": {"prompt_tokens": 11, "completion_tokens": 7},
        }
    )

    response = await LiteLLMProvider(completion).complete(request())

    assert completion.parameters["model"] == "openai/test-model"
    assert completion.parameters["stream"] is False
    assert completion.parameters["timeout"] == 1
    assert "tools" in completion.parameters
    assert completion.parameters["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "agentloom_output",
            "schema": request().response_schema,
            "strict": True,
        },
    }
    assert response.model == "provider/model-version"
    assert response.structured_output == {"answer": "done"}
    assert response.tool_calls[0].name == "lookup"
    assert response.tool_calls[0].arguments == {"query": "value"}
    assert response.input_tokens == 11
    assert response.output_tokens == 7


async def test_litellm_provider_supports_json_object_compatibility() -> None:
    completion = RecordingCompletion(
        {
            "choices": [{"message": {"content": '{"answer":"done"}', "tool_calls": None}}],
        }
    )

    response = await LiteLLMProvider(
        completion,
        response_format="json_object",
    ).complete(request())

    assert completion.parameters["response_format"] == {"type": "json_object"}
    assert response.structured_output == {"answer": "done"}


async def test_litellm_provider_rejects_invalid_tool_arguments_and_provider_errors() -> None:
    invalid_tool_completion = RecordingCompletion(
        {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "id": "call-1",
                                "function": {"name": "lookup", "arguments": "[]"},
                            }
                        ]
                    }
                }
            ]
        }
    )
    with pytest.raises(LLMResponseError, match="arguments must be a JSON object"):
        await LiteLLMProvider(invalid_tool_completion).complete(request())

    failed_completion = RecordingCompletion(RuntimeError("provider unavailable"))
    with pytest.raises(LLMResponseError, match="provider unavailable"):
        await LiteLLMProvider(failed_completion).complete(request())


async def test_litellm_provider_converts_timeout() -> None:
    async def slow_completion(**parameters: object) -> object:
        del parameters
        await asyncio.sleep(1)
        return {}

    with pytest.raises(LLMTimeoutError, match="timed out"):
        await LiteLLMProvider(slow_completion).complete(request(timeout_seconds=0.01))
