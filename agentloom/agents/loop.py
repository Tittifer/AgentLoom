"""The single multi-turn execution primitive used by queens and workers."""

import asyncio
import json
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID, uuid4

from pydantic import JsonValue

from agentloom.agents.judge import JudgePipeline
from agentloom.colony.schemas import ActorType, ColonyRead, MessageRead, SessionRead
from agentloom.llm.base import (
    LLMMessage,
    LLMProvider,
    LLMRequest,
    LLMResponseError,
    ToolCall,
    ToolDefinition,
)


@dataclass(frozen=True)
class LoopContext:
    session: SessionRead
    colony: ColonyRead
    messages: list[LLMMessage]


@dataclass(frozen=True)
class ToolExecutionResult:
    value: JsonValue
    terminate: bool = False


class AgentLoopStore(Protocol):
    async def load(self, session_id: UUID) -> LoopContext | None: ...

    async def mark_running(self, context: LoopContext) -> bool: ...

    async def append_message(
        self,
        context: LoopContext,
        message: LLMMessage,
        event_type: str,
        message_id: UUID | None = None,
    ) -> MessageRead: ...

    async def publish_message_delta(
        self,
        context: LoopContext,
        message_id: UUID,
        delta: str,
    ) -> None: ...

    async def cancel_message_stream(
        self,
        context: LoopContext,
        message_id: UUID,
    ) -> None: ...

    async def checkpoint(
        self,
        context: LoopContext,
        iteration: int,
        phase: str,
        usage: dict[str, int],
    ) -> None: ...

    async def finish(
        self,
        context: LoopContext,
        content: str,
        usage: dict[str, int],
    ) -> None: ...

    async def fail(self, context: LoopContext, error: Exception) -> None: ...


class AgentToolExecutor(Protocol):
    def definitions(self, actor_type: ActorType) -> list[ToolDefinition]: ...

    async def execute(
        self,
        context: LoopContext,
        tool_call: ToolCall,
    ) -> ToolExecutionResult: ...

    async def finalize_text(self, context: LoopContext, content: str) -> None: ...


class AgentLoop:
    """Stream-independent bounded LLM/tool/judge loop with durable turn boundaries."""

    def __init__(
        self,
        store: AgentLoopStore,
        provider: LLMProvider,
        tools: AgentToolExecutor,
        judge: JudgePipeline,
        *,
        default_max_turns: int,
        timeout_seconds: float,
    ) -> None:
        self._store = store
        self._provider = provider
        self._tools = tools
        self._judge = judge
        self._default_max_turns = default_max_turns
        self._timeout_seconds = timeout_seconds

    async def run(self, session_id: UUID) -> None:
        context = await self._store.load(session_id)
        if context is None or not await self._store.mark_running(context):
            return
        try:
            await self._run(context)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            await self._store.fail(context, error)

    async def _run(self, context: LoopContext) -> None:
        messages = [self._system_message(context), *context.messages]
        usage = self._initial_usage(context.session)
        configured_tool_calls = context.session.budget.get("max_tool_calls")
        max_tool_calls = configured_tool_calls if isinstance(configured_tool_calls, int) else 100
        configured_turns = context.session.budget.get("max_turns")
        max_turns = (
            configured_turns if isinstance(configured_turns, int) else self._default_max_turns
        )
        start_iteration = context.session.cursor.get("iteration")
        first_iteration = start_iteration + 1 if isinstance(start_iteration, int) else 1

        for iteration in range(first_iteration, max_turns + 1):
            request = LLMRequest(
                model=context.colony.model,
                messages=messages,
                tools=self._tools.definitions(context.session.actor_type),
                timeout_seconds=self._timeout_seconds,
            )
            message_id = uuid4()
            response = None
            stream_visible = False
            tool_calls_started = False
            try:
                async for chunk in self._provider.stream(request):
                    if chunk.tool_calls_started:
                        tool_calls_started = True
                        if stream_visible:
                            await self._store.cancel_message_stream(context, message_id)
                            stream_visible = False
                    if (
                        chunk.content_delta
                        and context.session.actor_type == "queen"
                        and not tool_calls_started
                    ):
                        await self._store.publish_message_delta(
                            context,
                            message_id,
                            chunk.content_delta,
                        )
                        stream_visible = True
                    if chunk.response is not None:
                        response = chunk.response
            except Exception:
                if stream_visible:
                    await self._store.cancel_message_stream(context, message_id)
                raise
            if response is None:
                if stream_visible:
                    await self._store.cancel_message_stream(context, message_id)
                raise LLMResponseError("Model stream ended without a terminal response")
            if response.tool_calls and stream_visible:
                await self._store.cancel_message_stream(context, message_id)
                stream_visible = False
            usage["input_tokens"] += response.input_tokens
            usage["output_tokens"] += response.output_tokens
            if (
                response.tool_calls
                and usage["tool_calls"] + len(response.tool_calls) > max_tool_calls
            ):
                raise RuntimeError(f"Agent exceeded {max_tool_calls} tool calls")
            content = response.content or self._json_content(response.structured_output)
            assistant = LLMMessage(
                role="assistant",
                content=content,
                tool_calls=response.tool_calls,
            )
            messages.append(assistant)
            await self._store.append_message(
                context,
                assistant,
                "message.completed",
                message_id,
            )

            if response.tool_calls:
                results = await asyncio.gather(
                    *(self._tools.execute(context, call) for call in response.tool_calls)
                )
                usage["tool_calls"] += len(results)
                for call, result in zip(response.tool_calls, results, strict=True):
                    tool_message = LLMMessage(
                        role="tool",
                        content=self._json_content(result.value),
                        tool_call_id=call.id,
                    )
                    messages.append(tool_message)
                    await self._store.append_message(context, tool_message, "tool.completed")
                await self._store.checkpoint(context, iteration, "after_tools", usage)
                if any(result.terminate for result in results):
                    return
                continue

            judgment = self._judge.review(content, iteration=iteration, max_turns=max_turns)
            if judgment.decision == "accept":
                await self._tools.finalize_text(context, content)
                await self._store.finish(context, content, usage)
                return
            if judgment.decision == "retry":
                feedback = LLMMessage(role="reviewer", content=judgment.model_dump_json())
                messages.append(feedback)
                await self._store.append_message(context, feedback, "judge.reviewed")
                await self._store.checkpoint(context, iteration, "judge_retry", usage)
                continue
            raise RuntimeError(judgment.feedback)

        raise RuntimeError(f"Agent exceeded {max_turns} model turns")

    @staticmethod
    def _system_message(context: LoopContext) -> LLMMessage:
        if context.session.actor_type == "queen":
            content = (
                "你是 AgentLoom Colony 的 Queen。持续与用户协作，维护计划和共享 Tracker。"
                "当任务可并行时调用 run_worker；Worker 报告会作为用户消息回到当前会话。"
                "不要虚构工具结果，最终回复必须使用中文。"
            )
        else:
            content = (
                "你是 Queen 派生的临时 Worker。只完成注入的单一任务，不得派生其他 Worker，"
                "不能等待用户回答。将结构化发现写入 Tracker，并用 report_to_parent 汇报。"
                f"任务：{json.dumps(context.session.task, ensure_ascii=False)}"
            )
        return LLMMessage(role="system", content=content)

    @staticmethod
    def _initial_usage(session: SessionRead) -> dict[str, int]:
        result: dict[str, int] = {}
        for key in ("input_tokens", "output_tokens", "tool_calls"):
            value = session.usage.get(key)
            result[key] = value if isinstance(value, int) else 0
        return result

    @staticmethod
    def _json_content(value: JsonValue | None) -> str:
        if value is None:
            return ""
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


__all__ = [
    "AgentLoop",
    "AgentLoopStore",
    "AgentToolExecutor",
    "LoopContext",
    "ToolExecutionResult",
]
