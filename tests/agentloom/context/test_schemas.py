"""Tests for context policy defaults and overrides."""

from agentloom.context.schemas import ContextPolicy


def test_context_policy_uses_hybrid_trigger_and_ignores_unrelated_budget_values() -> None:
    policy = ContextPolicy.from_mapping(
        {
            "max_context_tokens": 100_000,
            "compaction_buffer_tokens": 8_000,
            "compaction_buffer_ratio": 0.4,
            "max_turns": 20,
        }
    )

    assert policy.trigger_tokens == 52_000
    assert policy.max_tool_result_chars == 20_000
