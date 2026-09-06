"""Tests for structure-aware context compaction."""

from agentloom.context.compaction import ContextCompactor
from agentloom.context.schemas import ContextPolicy
from agentloom.llm.base import LLMMessage, LLMResponse
from agentloom.llm.mock import ScriptedMockLLMProvider


def test_microcompact_replaces_only_old_recoverable_tool_results() -> None:
    messages = [
        LLMMessage(
            role="tool",
            tool_call_id=f"call-{index}",
            content=(f'{{"full_result_file":"result-{index}.json","original_chars":50000}}'),
        )
        for index in range(8)
    ]

    compacted = ContextCompactor(1).microcompact(messages, keep_recent=2)

    assert '"compacted":true' in compacted[0].content
    assert '"compacted":true' not in compacted[-1].content


async def test_compactor_uses_bounded_auxiliary_request() -> None:
    provider = ScriptedMockLLMProvider([LLMResponse(content="保留目标和下一步", model="mock/test")])
    policy = ContextPolicy(
        max_context_tokens=8_192,
        compaction_buffer_tokens=0,
        compaction_buffer_ratio=0,
        compaction_summary_max_tokens=2_048,
    )

    summary = await ContextCompactor(1).summarize(
        [LLMMessage(role="user", content="完成分析并保留结论")],
        "mock/test",
        provider,
        policy,
    )

    assert summary == "保留目标和下一步"
    assert provider.requests[0].purpose == "compaction"
    assert provider.requests[0].max_output_tokens == 1_024
