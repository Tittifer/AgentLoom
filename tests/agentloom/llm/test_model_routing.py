"""Tests for Queen model-name protocol routing."""

from agentloom.llm.model_routing import (
    infer_model_protocol,
    litellm_model_name,
    protocol_api_base,
)


def test_protocol_is_inferred_from_model_name() -> None:
    assert infer_model_protocol("claude-sonnet-4") == "claude"
    assert infer_model_protocol("anthropic/claude-opus-4") == "claude"
    assert infer_model_protocol("gemini-2.5-pro") == "gemini"
    assert infer_model_protocol("deepseek-v4-flash") == "openai"
    assert infer_model_protocol("gpt-5") == "openai"


def test_litellm_routing_adds_protocol_details() -> None:
    assert litellm_model_name("claude-sonnet-4", "claude") == "anthropic/claude-sonnet-4"
    assert litellm_model_name("gemini/gemini-2.5-pro", "gemini") == "gemini/gemini-2.5-pro"
    assert litellm_model_name("openai/deepseek-v4-flash", "openai") == (
        "openai/deepseek-v4-flash"
    )
    assert protocol_api_base("https://api.example.com", "openai") == (
        "https://api.example.com/v1"
    )
    assert protocol_api_base("https://api.anthropic.com", "claude") == (
        "https://api.anthropic.com"
    )
