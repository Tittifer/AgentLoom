"""LiteLLM adapter for provider-neutral AgentLoom requests."""

import asyncio
import json
from collections.abc import AsyncIterable, AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass
from importlib import import_module
from typing import Literal, Protocol, cast, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError

from agentloom.llm.base import (
    LLMRequest,
    LLMResponse,
    LLMResponseError,
    LLMStreamChunk,
    LLMTimeoutError,
    ToolCall,
)
from agentloom.llm.model_routing import LLMProtocol, litellm_model_name, protocol_api_base

CompletionCallable = Callable[..., Awaitable[object]]
ResponseFormat = Literal["json_schema", "json_object"]
LITELLM_COMPLETION_ATTRIBUTE = "acompletion"


@runtime_checkable
class ModelDumpable(Protocol):
    """Structural boundary shared by Pydantic and LiteLLM response objects."""

    def model_dump(self) -> dict[str, object]: ...


class LiteFunction(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    arguments: str | dict[str, JsonValue]


class LiteToolCall(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    function: LiteFunction


class LiteMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    content: str | None = None
    reasoning_content: str | None = None
    parsed: dict[str, JsonValue] | None = None
    tool_calls: list[LiteToolCall] | None = None


class LiteChoice(BaseModel):
    model_config = ConfigDict(extra="ignore")

    message: LiteMessage


class LiteUsage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    prompt_tokens: int = 0
    completion_tokens: int = 0


class LiteResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    model: str | None = None
    choices: list[LiteChoice] = Field(min_length=1)
    usage: LiteUsage = Field(default_factory=LiteUsage)


class LiteDeltaFunction(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str | None = None
    arguments: str | None = None


class LiteDeltaToolCall(BaseModel):
    model_config = ConfigDict(extra="ignore")

    index: int = 0
    id: str | None = None
    function: LiteDeltaFunction | None = None


class LiteDelta(BaseModel):
    model_config = ConfigDict(extra="ignore")

    content: str | None = None
    reasoning_content: str | None = None
    tool_calls: list[LiteDeltaToolCall] | None = None


class LiteStreamChoice(BaseModel):
    model_config = ConfigDict(extra="ignore")

    delta: LiteDelta = Field(default_factory=LiteDelta)


class LiteStreamResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    model: str | None = None
    choices: list[LiteStreamChoice] = Field(default_factory=lambda: list[LiteStreamChoice]())
    usage: LiteUsage | None = None


@dataclass
class ToolCallBuffer:
    id: str = ""
    name: str = ""
    arguments: str = ""


class LiteLLMProvider:
    """Convert AgentLoom contracts to and from LiteLLM chat completions."""

    def __init__(
        self,
        completion: CompletionCallable | None = None,
        *,
        response_format: ResponseFormat = "json_schema",
        protocol: LLMProtocol | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self._completion = completion or _load_default_completion()
        self._response_format = response_format
        self._protocol: LLMProtocol | None = protocol
        self._base_url = base_url
        self._api_key = api_key

    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Execute one non-streaming completion with normalized errors and output."""

        parameters = self._parameters(request, stream=False)

        try:
            raw_response = await asyncio.wait_for(
                self._completion(**parameters),
                timeout=request.timeout_seconds,
            )
        except TimeoutError as error:
            raise LLMTimeoutError(f"Model {request.model} timed out") from error
        except Exception as error:
            raise LLMResponseError(f"LiteLLM request failed: {error}") from error

        return _normalize_response(raw_response, request)

    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMStreamChunk]:
        """Yield provider-native text deltas and one terminal normalized response."""

        parameters = self._parameters(request, stream=True)
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_calls: dict[int, ToolCallBuffer] = {}
        model = request.model
        usage = LiteUsage()
        try:
            raw_stream = await asyncio.wait_for(
                self._completion(**parameters),
                timeout=request.timeout_seconds,
            )
            if not isinstance(raw_stream, AsyncIterable):
                raise LLMResponseError("LiteLLM did not return an async stream")
            typed_stream = cast(AsyncIterable[object], raw_stream)

            async with asyncio.timeout(request.timeout_seconds):
                async for raw_chunk in typed_stream:
                    chunk = _normalize_stream_chunk(raw_chunk)
                    if chunk.model:
                        model = chunk.model
                    if chunk.usage is not None:
                        usage = chunk.usage
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta
                    if delta.content:
                        content_parts.append(delta.content)
                        yield LLMStreamChunk(content_delta=delta.content)
                    if delta.reasoning_content:
                        reasoning_parts.append(delta.reasoning_content)
                    if delta.tool_calls:
                        for tool_delta in delta.tool_calls:
                            buffer = tool_calls.setdefault(tool_delta.index, ToolCallBuffer())
                            if tool_delta.id:
                                buffer.id += tool_delta.id
                            if tool_delta.function is not None:
                                if tool_delta.function.name:
                                    buffer.name += tool_delta.function.name
                                if tool_delta.function.arguments:
                                    buffer.arguments += tool_delta.function.arguments
                        yield LLMStreamChunk(tool_calls_started=True)
        except TimeoutError as error:
            raise LLMTimeoutError(f"Model {request.model} timed out") from error
        except LLMResponseError:
            raise
        except Exception as error:
            raise LLMResponseError(f"LiteLLM stream failed: {error}") from error

        content = "".join(content_parts) or None
        reasoning_content = "".join(reasoning_parts) or None
        normalized_calls = [
            _normalize_tool_call(
                LiteToolCall(
                    id=buffer.id,
                    function=LiteFunction(name=buffer.name, arguments=buffer.arguments),
                )
            )
            for _, buffer in sorted(tool_calls.items())
        ]
        yield LLMStreamChunk(
            response=LLMResponse(
                content=content,
                reasoning_content=reasoning_content,
                structured_output=_structured_output(content, request),
                tool_calls=normalized_calls,
                input_tokens=usage.prompt_tokens,
                output_tokens=usage.completion_tokens,
                model=model,
            )
        )

    def _parameters(self, request: LLMRequest, *, stream: bool) -> dict[str, object]:
        fill_missing_reasoning = _requires_reasoning_content(request.model)
        model = (
            litellm_model_name(request.model, self._protocol)
            if self._protocol is not None
            else request.model
        )
        parameters: dict[str, object] = {
            "model": model,
            "messages": [
                _message_payload(message, fill_missing_reasoning=fill_missing_reasoning)
                for message in request.messages
            ],
            "stream": stream,
            "timeout": request.timeout_seconds,
        }
        if self._protocol is not None and self._base_url is not None:
            parameters["api_base"] = protocol_api_base(self._base_url, self._protocol)
        if self._api_key is not None:
            parameters["api_key"] = self._api_key
        if request.tools:
            parameters["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters,
                    },
                }
                for tool in request.tools
            ]
        if request.response_schema is not None:
            if self._response_format == "json_object":
                parameters["response_format"] = {"type": "json_object"}
            else:
                parameters["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "agentloom_output",
                        "schema": request.response_schema,
                        "strict": True,
                    },
                }
        return parameters


def _load_default_completion() -> CompletionCallable:
    """Import LiteLLM only when the real provider is actually selected."""

    module = import_module("litellm")
    return cast(
        CompletionCallable,
        getattr(module, LITELLM_COMPLETION_ATTRIBUTE),
    )


def _message_payload(
    message: object,
    *,
    fill_missing_reasoning: bool = False,
) -> dict[str, object]:
    from agentloom.llm.base import LLMMessage

    normalized = LLMMessage.model_validate(message)
    payload: dict[str, object] = {
        "role": normalized.role,
        "content": normalized.content,
    }
    if (
        fill_missing_reasoning
        and normalized.role == "assistant"
        and not normalized.reasoning_content
    ):
        payload["reasoning_content"] = " "
    elif normalized.reasoning_content is not None:
        payload["reasoning_content"] = normalized.reasoning_content
    if normalized.tool_call_id is not None:
        payload["tool_call_id"] = normalized.tool_call_id
    if normalized.tool_calls:
        payload["tool_calls"] = [
            {
                "id": tool_call.id,
                "type": "function",
                "function": {
                    "name": tool_call.name,
                    "arguments": json.dumps(tool_call.arguments, ensure_ascii=False),
                },
            }
            for tool_call in normalized.tool_calls
        ]
    return payload


def _requires_reasoning_content(model: str) -> bool:
    return any(part.startswith("deepseek") for part in model.lower().split("/"))


def _normalize_response(raw_response: object, request: LLMRequest) -> LLMResponse:
    try:
        response = LiteResponse.model_validate(_response_mapping(raw_response))
    except ValidationError as error:
        raise LLMResponseError(f"LiteLLM returned an invalid response: {error}") from error

    message = response.choices[0].message
    tool_calls = [_normalize_tool_call(tool_call) for tool_call in message.tool_calls or []]
    structured_output = message.parsed or _structured_output(message.content, request)

    return LLMResponse(
        content=message.content,
        reasoning_content=message.reasoning_content,
        structured_output=structured_output,
        tool_calls=tool_calls,
        input_tokens=response.usage.prompt_tokens,
        output_tokens=response.usage.completion_tokens,
        model=response.model or request.model,
    )


def _normalize_stream_chunk(raw_chunk: object) -> LiteStreamResponse:
    try:
        return LiteStreamResponse.model_validate(_response_mapping(raw_chunk))
    except ValidationError as error:
        raise LLMResponseError(f"LiteLLM returned an invalid stream chunk: {error}") from error


def _structured_output(content: str | None, request: LLMRequest) -> dict[str, JsonValue] | None:
    if request.response_schema is None or not content:
        return None
    try:
        parsed_content = json.loads(content)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed_content, dict):
        return cast(dict[str, JsonValue], parsed_content)
    return None


def _response_mapping(raw_response: object) -> Mapping[str, object]:
    if isinstance(raw_response, Mapping):
        return cast(Mapping[str, object], raw_response)
    if isinstance(raw_response, ModelDumpable):
        return raw_response.model_dump()
    raise LLMResponseError("LiteLLM returned a response without a serializable model")


def _normalize_tool_call(tool_call: LiteToolCall) -> ToolCall:
    arguments = tool_call.function.arguments
    if isinstance(arguments, str):
        try:
            parsed_arguments = json.loads(arguments)
        except json.JSONDecodeError:
            return ToolCall(
                id=tool_call.id,
                name=tool_call.function.name,
                arguments={},
                argument_error=(
                    f"工具 {tool_call.function.name} 的参数不是合法 JSON，"
                    "请重新生成完整的 JSON 对象。"
                ),
            )
        if not isinstance(parsed_arguments, dict):
            return ToolCall(
                id=tool_call.id,
                name=tool_call.function.name,
                arguments={},
                argument_error=(
                    f"工具 {tool_call.function.name} 的参数必须是 JSON 对象，请重新生成参数。"
                ),
            )
        arguments = cast(dict[str, JsonValue], parsed_arguments)
    return ToolCall(
        id=tool_call.id,
        name=tool_call.function.name,
        arguments=arguments,
    )


__all__ = ["CompletionCallable", "LiteLLMProvider", "ResponseFormat"]
