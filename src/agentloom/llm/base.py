"""Provider-neutral language-model request and response contracts."""

from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, JsonValue

JsonObject = dict[str, JsonValue]
MessageRole = Literal["system", "user", "assistant", "tool", "reviewer"]


class LLMModel(BaseModel):
    """Strict base model for data crossing an LLM provider boundary."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ToolCall(LLMModel):
    """One normalized function-style tool request from a model."""

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    arguments: JsonObject = Field(default_factory=dict)


class ToolDefinition(LLMModel):
    """One callable tool exposed to a model."""

    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    parameters: JsonObject


class LLMMessage(LLMModel):
    """One provider-neutral visible conversation message."""

    role: MessageRole
    content: str
    tool_call_id: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=lambda: list[ToolCall]())


class LLMRequest(LLMModel):
    """One bounded model completion request."""

    model: str = Field(min_length=1)
    messages: list[LLMMessage] = Field(min_length=1)
    tools: list[ToolDefinition] = Field(default_factory=lambda: list[ToolDefinition]())
    response_schema: JsonObject | None = None
    timeout_seconds: float = Field(default=60, gt=0, le=600)


class LLMResponse(LLMModel):
    """Normalized completion result returned by every provider."""

    content: str | None = None
    structured_output: JsonObject | None = None
    tool_calls: list[ToolCall] = Field(default_factory=lambda: list[ToolCall]())
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    model: str = Field(min_length=1)


class LLMProvider(Protocol):
    """Runtime interface implemented by mock and real model adapters."""

    async def complete(self, request: LLMRequest) -> LLMResponse: ...


class LLMProviderError(RuntimeError):
    """Base error for failures at the model-provider boundary."""


class LLMTimeoutError(LLMProviderError):
    """Raised when a model call exceeds its configured deadline."""


class LLMResponseError(LLMProviderError):
    """Raised when a provider response cannot be normalized safely."""


__all__ = [
    "JsonObject",
    "LLMMessage",
    "LLMProvider",
    "LLMProviderError",
    "LLMRequest",
    "LLMResponse",
    "LLMResponseError",
    "LLMTimeoutError",
    "MessageRole",
    "ToolCall",
    "ToolDefinition",
]
