"""Conservative provider-neutral token estimates."""

from __future__ import annotations

import json
import unicodedata
from collections.abc import Sequence

from agentloom.llm.base import LLMMessage, ToolDefinition


def estimate_text_tokens(value: str) -> int:
    ascii_chars = 0
    wide_chars = 0
    for character in value:
        if ord(character) < 128:
            ascii_chars += 1
        elif unicodedata.east_asian_width(character) in {"W", "F", "A"}:
            wide_chars += 1
        else:
            ascii_chars += 1
    return wide_chars + (ascii_chars + 3) // 4


def estimate_context_tokens(
    messages: Sequence[LLMMessage],
    tools: Sequence[ToolDefinition] = (),
) -> int:
    total = 0
    for message in messages:
        total += 4 + estimate_text_tokens(message.content)
        if message.reasoning_content:
            total += estimate_text_tokens(message.reasoning_content)
        if message.tool_calls:
            total += estimate_text_tokens(
                json.dumps(
                    [call.model_dump(mode="json") for call in message.tool_calls],
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            )
    if tools:
        total += estimate_text_tokens(
            json.dumps(
                [tool.model_dump(mode="json") for tool in tools],
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
    return total


__all__ = ["estimate_context_tokens", "estimate_text_tokens"]
