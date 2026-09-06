"""Tests for conservative token estimation."""

from agentloom.context.estimator import estimate_context_tokens, estimate_text_tokens
from agentloom.llm.base import LLMMessage, ToolDefinition


def test_estimator_counts_wide_characters_more_conservatively_than_ascii() -> None:
    assert estimate_text_tokens("测试上下文") == 5
    assert estimate_text_tokens("abcdefgh") == 2
    assert (
        estimate_context_tokens(
            [LLMMessage(role="user", content="测试")],
            [ToolDefinition(name="lookup", description="查询", parameters={})],
        )
        > 6
    )
