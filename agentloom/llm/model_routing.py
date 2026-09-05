"""Derive provider protocol details from a Queen model name."""

from typing import Literal

LLMProtocol = Literal["openai", "claude", "gemini"]


def infer_model_protocol(model: str) -> LLMProtocol:
    """Select the native API protocol implied by a model name."""

    normalized = model.strip().lower()
    model_name = normalized.rsplit("/", 1)[-1]
    if normalized.startswith(("anthropic/", "claude/")) or model_name.startswith("claude"):
        return "claude"
    if normalized.startswith(("gemini/", "google/")) or model_name.startswith("gemini"):
        return "gemini"
    return "openai"


def litellm_model_name(model: str, protocol: LLMProtocol) -> str:
    """Return the LiteLLM routing name for one native protocol."""

    normalized = model.strip()
    prefix, separator, remainder = normalized.partition("/")
    if separator and prefix.lower() in {"openai", "anthropic", "claude", "gemini", "google"}:
        normalized = remainder
    provider_prefix = "anthropic" if protocol == "claude" else protocol
    return f"{provider_prefix}/{normalized}"


def protocol_api_base(base_url: str, protocol: LLMProtocol) -> str:
    """Add only the suffix required by the selected protocol."""

    normalized = base_url.rstrip("/")
    return f"{normalized}/v1" if protocol == "openai" else normalized


__all__ = ["LLMProtocol", "infer_model_protocol", "litellm_model_name", "protocol_api_base"]
