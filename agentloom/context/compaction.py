"""Hive-style structure-aware context compaction."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import cast

import structlog

from agentloom.context.estimator import estimate_context_tokens
from agentloom.context.schemas import CompactionCheckpoint, ContextPolicy, checkpoint_now
from agentloom.llm.base import (
    LLMContextLengthError,
    LLMMessage,
    LLMProvider,
    LLMRequest,
    ToolDefinition,
)
from agentloom.storage.base import utc_now

MAX_SPLIT_DEPTH = 8
KEEP_RECENT_GROUPS = 2
COMPACTION_SYSTEM_PROMPT = (
    "你是 AgentLoom 的上下文压缩器。生成一份能让智能体无缝继续工作的详细中文摘要。"
    "必须保留用户规则、限制、关键决定、已完成工作、错误、工具文件指针、待办事项和下一步。"
    "不得创造事实，不得输出对话之外的建议。"
)


class ContextCompactor:
    def __init__(self, timeout_seconds: float) -> None:
        self._timeout_seconds = timeout_seconds
        self._logger = structlog.get_logger(__name__)

    def needs_compaction(
        self,
        messages: Sequence[LLMMessage],
        tools: Sequence[ToolDefinition],
        policy: ContextPolicy,
    ) -> bool:
        return estimate_context_tokens(messages, tools) >= policy.trigger_tokens

    def microcompact(
        self, messages: Sequence[LLMMessage], keep_recent: int = 6
    ) -> list[LLMMessage]:
        result = list(messages)
        recoverable: list[int] = []
        for index in range(len(result) - 1, -1, -1):
            message = result[index]
            if message.role != "tool" or "full_result_file" not in message.content:
                continue
            recoverable.append(index)
        for index in recoverable[keep_recent:]:
            message = result[index]
            try:
                payload_value = cast(object, json.loads(message.content))
            except json.JSONDecodeError:
                continue
            if not isinstance(payload_value, dict):
                continue
            payload = cast(dict[str, object], payload_value)
            filename = payload.get("full_result_file") or payload.get("_agentloom_full_result_file")
            raw_original_chars = payload.get("original_chars")
            original_chars = (
                raw_original_chars if isinstance(raw_original_chars, int) else len(message.content)
            )
            if not isinstance(filename, str):
                continue
            result[index] = message.model_copy(
                update={
                    "content": json.dumps(
                        {
                            "compacted": True,
                            "original_chars": original_chars,
                            "full_result_file": filename,
                            "hint": "使用 load_tool_result 按需读取完整结果。",
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                }
            )
        return result

    async def summarize(
        self,
        messages: Sequence[LLMMessage],
        model: str,
        provider: LLMProvider,
        policy: ContextPolicy,
        *,
        depth: int = 0,
    ) -> str:
        if depth > MAX_SPLIT_DEPTH:
            raise RuntimeError("上下文压缩递归深度已超过限制")
        formatted = self._format_messages(messages)
        char_limit = max(20_000, policy.max_context_tokens)
        if len(formatted) > char_limit and len(messages) > 1:
            middle = max(1, len(messages) // 2)
            first = await self.summarize(
                messages[:middle], model, provider, policy, depth=depth + 1
            )
            second = await self.summarize(
                messages[middle:], model, provider, policy, depth=depth + 1
            )
            return f"{first}\n\n{second}"
        try:
            response = await provider.complete(
                LLMRequest(
                    model=model,
                    messages=[
                        LLMMessage(role="system", content=COMPACTION_SYSTEM_PROMPT),
                        LLMMessage(
                            role="user",
                            content=(
                                "请按以下栏目压缩：主要目标、用户约束、关键决定、已完成工作、"
                                "文件与工具数据、错误与处理、未完成事项、当前状态与下一步。\n\n"
                                f"{formatted}"
                            ),
                        ),
                    ],
                    timeout_seconds=self._timeout_seconds,
                    max_output_tokens=min(
                        policy.compaction_summary_max_tokens,
                        max(1_024, policy.max_context_tokens // 8),
                    ),
                    purpose="compaction",
                )
            )
        except LLMContextLengthError:
            if len(messages) <= 1:
                raise
            middle = max(1, len(messages) // 2)
            first = await self.summarize(
                messages[:middle], model, provider, policy, depth=depth + 1
            )
            second = await self.summarize(
                messages[middle:], model, provider, policy, depth=depth + 1
            )
            return f"{first}\n\n{second}"
        if not response.content or not response.content.strip():
            raise RuntimeError("上下文压缩模型返回了空摘要")
        return response.content.strip()

    def build_checkpoint(
        self,
        summary: str,
        through_sequence: int,
        preserved_sequences: list[int],
        tokens_before: int,
        recent_messages: Sequence[LLMMessage],
    ) -> CompactionCheckpoint:
        compacted = [LLMMessage(role="user", content=summary), *recent_messages]
        return checkpoint_now(
            summary,
            through_sequence,
            preserved_sequences,
            tokens_before,
            estimate_context_tokens(compacted),
            utc_now(),
        )

    @staticmethod
    def recent_start(messages: Sequence[LLMMessage]) -> int:
        if len(messages) <= 2:
            return 0
        groups = 0
        index = len(messages)
        while index > 0 and groups < KEEP_RECENT_GROUPS:
            index -= 1
            if messages[index].role != "tool":
                groups += 1
        while index > 0 and messages[index].role == "tool":
            index -= 1
        return index

    @staticmethod
    def _format_messages(messages: Sequence[LLMMessage]) -> str:
        blocks: list[str] = []
        for message in messages:
            content = message.content
            if message.role == "tool" and len(content) > 1_000:
                content = content[:1_000] + "…"
            calls = ""
            if message.tool_calls:
                calls = " tools=" + ",".join(call.name for call in message.tool_calls)
            blocks.append(f"[{message.role}{calls}] {content}")
        return "\n\n".join(blocks)


__all__ = ["ContextCompactor"]
