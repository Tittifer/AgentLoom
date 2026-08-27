"""Test-only ASGI application with one deterministic reviewer retry."""

import asyncio

import agentloom.bootstrap as bootstrap
from agentloom.config import Settings
from agentloom.llm.base import LLMProvider, LLMRequest, LLMResponse
from agentloom.llm.mock import SchemaMockLLMProvider


class RetryOnceSchemaMockLLMProvider(SchemaMockLLMProvider):
    """Return one invalid Apple research result before normal schema-shaped output."""

    def __init__(self) -> None:
        super().__init__("mock/e2e")
        self._retried = False
        self._lock = asyncio.Lock()

    async def complete(self, request: LLMRequest) -> LLMResponse:
        required_fields = (
            request.response_schema.get("required")
            if request.response_schema is not None
            else None
        )
        is_apple_worker = (
            required_fields == ["summary", "sources"]
            and any(
                "Research subject A for the requested comparison" in message.content
                for message in request.messages
            )
        )
        if is_apple_worker:
            async with self._lock:
                if not self._retried:
                    self._retried = True
                    self.requests.append(request.model_copy(deep=True))
                    return LLMResponse(
                        structured_output={"summary": "", "sources": []},
                        input_tokens=10,
                        output_tokens=5,
                        model="mock/e2e",
                    )
        return await super().complete(request)


provider = RetryOnceSchemaMockLLMProvider()


def create_e2e_provider(_: Settings) -> LLMProvider:
    return provider


bootstrap.create_llm_provider = create_e2e_provider

from agentloom.main import create_app  # noqa: E402

app = create_app(
    Settings(
        environment="test",
        log_level="WARNING",
        llm_provider="mock",
        llm_model="mock/e2e",
    )
)
