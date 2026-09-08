"""Construct an LLM provider from the global user configuration."""

from agentloom.llm.base import LLMProvider
from agentloom.llm.litellm_provider import LiteLLMProvider
from agentloom.user_settings import UserLLMRuntimeConfig


def create_llm_provider(settings: UserLLMRuntimeConfig) -> LLMProvider:
    """Create a provider shared by Queen and Worker loops."""

    return LiteLLMProvider(
        protocol=settings.protocol,
        base_url=settings.base_url,
        api_key=settings.api_key,
        response_format=settings.response_format,
    )


__all__ = ["create_llm_provider"]
