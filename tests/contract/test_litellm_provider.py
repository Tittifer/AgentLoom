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
    messages = completion.parameters["messages"]
    assert isinstance(messages, list)
    assert "reasoning_content" not in messages[0]
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


async def test_litellm_provider_round_trips_reasoning_content() -> None:
    completion = RecordingCompletion(
        {
            "model": "provider/model-version",
            "choices": [
                {
                    "message": {
                        "content": "完成",
                        "reasoning_content": "  provider reasoning  ",
                    }
                }
            ],
        }
    )
    reasoning_request = request().model_copy(
        update={
            "messages": [
                LLMMessage(
                    role="assistant",
                    content="处理中",
                    reasoning_content="  previous reasoning  ",
                ),
                LLMMessage(role="user", content="继续"),
            ]
        }
    )

    response = await LiteLLMProvider(completion).complete(reasoning_request)

    messages = completion.parameters["messages"]
    assert isinstance(messages, list)
    assert messages[0]["reasoning_content"] == "  previous reasoning  "
    assert response.reasoning_content == "  provider reasoning  "


async def test_litellm_provider_fills_missing_reasoning_for_openai_routed_deepseek() -> None:
    completion = RecordingCompletion(
        {"choices": [{"message": {"content": "完成"}}]},
    )
    deepseek_request = request().model_copy(
        update={
            "model": "openai/deepseek-v4-flash",
            "messages": [
                LLMMessage(role="assistant", content="阶段性结果"),
                LLMMessage(role="user", content="继续"),
            ],
        }
    )

    await LiteLLMProvider(completion).complete(deepseek_request)

    messages = completion.parameters["messages"]
    assert isinstance(messages, list)
    assert messages[0]["reasoning_content"] == " "
    assert "reasoning_content" not in messages[1]


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


async def test_litellm_provider_normalizes_invalid_tool_arguments() -> None:
    invalid_json_completion = RecordingCompletion(
        {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "id": "call-invalid-json",
                                "function": {"name": "lookup", "arguments": '{"query":'},
                            }
                        ]
                    }
                }
            ]
        }
    )
    invalid_json_response = await LiteLLMProvider(invalid_json_completion).complete(request())

    invalid_json_call = invalid_json_response.tool_calls[0]
    assert invalid_json_call.arguments == {}
    assert invalid_json_call.argument_error is not None
    assert "不是合法 JSON" in invalid_json_call.argument_error
    assert "argument_error" not in invalid_json_call.model_dump()

    non_object_completion = RecordingCompletion(
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
    non_object_response = await LiteLLMProvider(non_object_completion).complete(request())

    non_object_call = non_object_response.tool_calls[0]
    assert non_object_call.arguments == {}
    assert non_object_call.argument_error is not None
    assert "必须是 JSON 对象" in non_object_call.argument_error


async def test_litellm_provider_converts_provider_errors() -> None:
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


async def test_litellm_provider_streams_native_text_deltas_and_terminal_usage() -> None:
    async def chunks():  # type: ignore[no-untyped-def]
        yield {"choices": [{"delta": {"reasoning_content": "  first "}}]}
        yield {
            "model": "provider/model-version",
            "choices": [{"delta": {"reasoning_content": "second  ", "content": '{"answer":"'}}],
        }
        yield {"choices": [{"delta": {"content": "完成"}}]}
        yield {
            "choices": [{"delta": {"content": '"}'}}],
            "usage": {"prompt_tokens": 13, "completion_tokens": 4},
        }

    completion = RecordingCompletion(chunks())
    streamed = [chunk async for chunk in LiteLLMProvider(completion).stream(request())]

    assert completion.parameters["stream"] is True
    assert [chunk.content_delta for chunk in streamed[:-1]] == [
        '{"answer":"',
        "完成",
        '"}',
    ]
    response = streamed[-1].response
    assert response is not None
    assert response.content == '{"answer":"完成"}'
    assert response.reasoning_content == "  first second  "
    assert response.structured_output == {"answer": "完成"}
    assert response.input_tokens == 13
    assert response.output_tokens == 4


async def test_litellm_provider_accumulates_fragmented_stream_tool_calls() -> None:
    async def chunks():  # type: ignore[no-untyped-def]
        yield {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call-1",
                                "function": {"name": "lookup", "arguments": '{"query":"'},
                            }
                        ]
                    }
                }
            ]
        }
        yield {
            "choices": [
                {"delta": {"tool_calls": [{"index": 0, "function": {"arguments": 'value"}'}}]}}
            ]
        }

    streamed = [
        chunk async for chunk in LiteLLMProvider(RecordingCompletion(chunks())).stream(request())
    ]

    assert streamed[0].tool_calls_started
    response = streamed[-1].response
    assert response is not None
    assert response.tool_calls[0].id == "call-1"
    assert response.tool_calls[0].name == "lookup"
    assert response.tool_calls[0].arguments == {"query": "value"}


async def test_litellm_provider_times_out_while_consuming_stream() -> None:
    async def chunks():  # type: ignore[no-untyped-def]
        await asyncio.sleep(1)
        yield {"choices": [{"delta": {"content": "too late"}}]}

    provider = LiteLLMProvider(RecordingCompletion(chunks()))
    with pytest.raises(LLMTimeoutError, match="timed out"):
        _ = [chunk async for chunk in provider.stream(request(timeout_seconds=0.01))]
