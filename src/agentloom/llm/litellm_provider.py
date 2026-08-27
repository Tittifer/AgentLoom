"""LiteLLM adapter for provider-neutral AgentLoom requests."""

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping
from importlib import import_module
from typing import Literal, Protocol, cast, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError

from agentloom.llm.base import (
    LLMRequest,
    LLMResponse,
    LLMResponseError,
    LLMTimeoutError,
    ToolCall,
)

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


class LiteLLMProvider:
    """Convert AgentLoom contracts to and from LiteLLM chat completions."""

    def __init__(
        self,
        completion: CompletionCallable | None = None,
        *,
        response_format: ResponseFormat = "json_schema",
    ) -> None:
        self._completion = completion or _load_default_completion()
        self._response_format = response_format

    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Execute one non-streaming completion with normalized errors and output."""

        parameters: dict[str, object] = {
            "model": request.model,
            "messages": [_message_payload(message) for message in request.messages],
            "stream": False,
            "timeout": request.timeout_seconds,
        }
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


def _load_default_completion() -> CompletionCallable:
    """Import LiteLLM only when the real provider is actually selected."""

    module = import_module("litellm")
    return cast(
        CompletionCallable,
        getattr(module, LITELLM_COMPLETION_ATTRIBUTE),
    )


def _message_payload(message: object) -> dict[str, object]:
    from agentloom.llm.base import LLMMessage

    normalized = LLMMessage.model_validate(message)
    payload: dict[str, object] = {
        "role": normalized.role,
        "content": normalized.content,
    }
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


def _normalize_response(raw_response: object, request: LLMRequest) -> LLMResponse:
    try:
        response = LiteResponse.model_validate(_response_mapping(raw_response))
    except ValidationError as error:
        raise LLMResponseError(f"LiteLLM returned an invalid response: {error}") from error

    message = response.choices[0].message
    tool_calls = [_normalize_tool_call(tool_call) for tool_call in message.tool_calls or []]
    structured_output = message.parsed
    if structured_output is None and request.response_schema is not None and message.content:
        try:
            parsed_content = json.loads(message.content)
        except json.JSONDecodeError:
            parsed_content = None
        if isinstance(parsed_content, dict):
            structured_output = cast(dict[str, JsonValue], parsed_content)

    return LLMResponse(
        content=message.content,
        structured_output=structured_output,
        tool_calls=tool_calls,
        input_tokens=response.usage.prompt_tokens,
        output_tokens=response.usage.completion_tokens,
        model=response.model or request.model,
    )


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
        except json.JSONDecodeError as error:
            raise LLMResponseError(
                f"Tool {tool_call.function.name} returned invalid JSON arguments"
            ) from error
        if not isinstance(parsed_arguments, dict):
            raise LLMResponseError(
                f"Tool {tool_call.function.name} arguments must be a JSON object"
            )
        arguments = cast(dict[str, JsonValue], parsed_arguments)
    return ToolCall(
        id=tool_call.id,
        name=tool_call.function.name,
        arguments=arguments,
    )


__all__ = ["CompletionCallable", "LiteLLMProvider", "ResponseFormat"]
