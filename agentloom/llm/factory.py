"""Construct an LLM provider from one Queen's persisted configuration."""

from agentloom.colony.schemas import QueenRuntimeConfig
from agentloom.llm.base import LLMProvider
from agentloom.llm.litellm_provider import LiteLLMProvider


def create_queen_llm_provider(queen: QueenRuntimeConfig) -> LLMProvider:
    """Create an isolated provider using only the Queen YAML configuration."""

    return LiteLLMProvider(
        protocol=queen.protocol,
        base_url=queen.base_url,
        api_key=queen.api_key,
    )


__all__ = ["create_queen_llm_provider"]
