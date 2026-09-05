"""The single multi-turn execution primitive used by queens and workers."""

import asyncio
import json
from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID, uuid4

import structlog
from pydantic import JsonValue

from agentloom.agents.judge import JudgePipeline
from agentloom.colony.schemas import ActorType, ColonyRead, MessageRead, SessionRead
from agentloom.llm.base import (
    LLMMessage,
    LLMProvider,
    LLMRequest,
    LLMResponse,
    LLMResponseError,
    ToolCall,
    ToolDefinition,
)

BudgetReason = Literal["model_turns", "tool_calls"]

GRACE_TERMINAL_TOOL_NAMES = frozenset({"report_to_parent", "tracker_upsert", "task_update"})
DEFAULT_GRACE_TURNS = {"queen": 1, "worker": 2}


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
        *,
        budget_tool_calls: int = 0,
        budget_reason: BudgetReason | None = None,
        grace_turn: int = 0,
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

    async def finalize_budget_exhausted(
        self,
        context: LoopContext,
        content: str,
        reason: BudgetReason,
    ) -> None: ...


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
        self._logger = structlog.get_logger(__name__)

    async def run(self, session_id: UUID) -> None:
        context = await self._store.load(session_id)
        if context is None:
            return
        try:
            if not await self._store.mark_running(context):
                return
            await self._run(context)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            await self._store.fail(context, error)

    async def _run(self, context: LoopContext) -> None:
        messages = [self._system_message(context), *context.messages]
        usage = self._initial_usage(context.session)
        configured_tool_calls = context.session.budget.get("max_tool_calls")
        max_tool_calls = (
            configured_tool_calls
            if isinstance(configured_tool_calls, int) and configured_tool_calls >= 0
            else 100
        )
        configured_turns = context.session.budget.get("max_turns")
        max_turns = (
            configured_turns
            if isinstance(configured_turns, int) and configured_turns > 0
            else self._default_max_turns
        )
        configured_grace_turns = context.session.budget.get("grace_turns")
        grace_turns = (
            configured_grace_turns
            if isinstance(configured_grace_turns, int) and configured_grace_turns >= 0
            else DEFAULT_GRACE_TURNS[context.session.actor_type]
        )
        last_work_iteration = self._non_negative_int(context.session.cursor.get("iteration"))
        next_work_iteration = last_work_iteration + 1
        budget_tool_calls = self._initial_budget_tool_calls(context.session, usage)
        budget_reason = self._restored_budget_reason(context.session)
        grace_turn = (
            self._non_negative_int(context.session.cursor.get("grace_turn"))
            if budget_reason is not None
            else 0
        )
        if budget_reason is not None:
            messages.append(
                LLMMessage(
                    role="system",
                    content=self._budget_reminder(context, budget_reason),
                )
            )

        while True:
            if budget_reason is None:
                if next_work_iteration > max_turns:
                    budget_reason = "model_turns"
                elif budget_tool_calls >= max_tool_calls:
                    budget_reason = "tool_calls"
                if budget_reason is not None:
                    await self._enter_budget_grace(
                        context,
                        messages,
                        last_work_iteration,
                        usage,
                        budget_tool_calls,
                        budget_reason,
                    )

            if budget_reason is not None and grace_turn >= grace_turns:
                await self._finish_budget_exhausted(
                    context,
                    budget_reason,
                    usage,
                    budget_tool_calls,
                    grace_turn,
                )
                return

            in_grace = budget_reason is not None
            iteration = last_work_iteration + grace_turn + 1 if in_grace else next_work_iteration
            definitions = self._tools.definitions(context.session.actor_type)
            if in_grace:
                allowed_names = (
                    GRACE_TERMINAL_TOOL_NAMES
                    if context.session.actor_type == "worker"
                    else frozenset[str]()
                )
                definitions = [
                    definition for definition in definitions if definition.name in allowed_names
                ]
            response, message_id = await self._complete_turn(
                context,
                messages,
                definitions,
                usage,
                iteration,
            )
            content = response.content or self._json_content(response.structured_output)
            assistant = LLMMessage(
                role="assistant",
                content=content,
                reasoning_content=response.reasoning_content,
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
                results, executed_count, tool_budget_exhausted = await self._execute_tool_calls(
                    context,
                    response.tool_calls,
                    definitions,
                    in_grace=in_grace,
                    remaining_budget=max_tool_calls - budget_tool_calls,
                )
                usage["tool_calls"] += executed_count
                if not in_grace:
                    budget_tool_calls += executed_count
                for call, result in zip(response.tool_calls, results, strict=True):
                    tool_message = LLMMessage(
                        role="tool",
                        content=self._json_content(result.value),
                        tool_call_id=call.id,
                    )
                    messages.append(tool_message)
                    await self._store.append_message(context, tool_message, "tool.completed")
                if in_grace:
                    grace_turn += 1
                else:
                    last_work_iteration = iteration
                    next_work_iteration = iteration + 1
                self._logger.info(
                    "agent_tool_usage",
                    session_id=str(context.session.id),
                    actor_type=context.session.actor_type,
                    iteration=iteration,
                    in_grace=in_grace,
                    requested_tool_calls=len(response.tool_calls),
                    executed_tool_calls=executed_count,
                    skipped_tool_calls=len(response.tool_calls) - executed_count,
                    work_budget_tool_calls=budget_tool_calls,
                    total_tool_calls=usage["tool_calls"],
                )
                if any(result.terminate for result in results):
                    await self._store.finish(context, content, usage)
                    return
                await self._store.checkpoint(
                    context,
                    last_work_iteration,
                    "budget_grace" if in_grace else "after_tools",
                    usage,
                    budget_tool_calls=budget_tool_calls,
                    budget_reason=budget_reason,
                    grace_turn=grace_turn,
                )
                if not in_grace and tool_budget_exhausted:
                    budget_reason = "tool_calls"
                    await self._enter_budget_grace(
                        context,
                        messages,
                        last_work_iteration,
                        usage,
                        budget_tool_calls,
                        budget_reason,
                    )
                continue

            if in_grace:
                if budget_reason is None:
                    raise RuntimeError("Budget grace is missing its trigger reason")
                grace_turn += 1
                if content.strip():
                    await self._tools.finalize_budget_exhausted(
                        context,
                        content,
                        budget_reason,
                    )
                    await self._store.finish(context, content, usage)
                    self._log_budget_completion(
                        context,
                        budget_reason,
                        budget_tool_calls,
                        grace_turn,
                        fallback=False,
                    )
                    return
                await self._store.checkpoint(
                    context,
                    last_work_iteration,
                    "budget_grace",
                    usage,
                    budget_tool_calls=budget_tool_calls,
                    budget_reason=budget_reason,
                    grace_turn=grace_turn,
                )
                continue

            last_work_iteration = iteration
            next_work_iteration = iteration + 1
            judgment = self._judge.review(content, iteration=iteration, max_turns=max_turns)
            if judgment.decision == "accept":
                await self._tools.finalize_text(context, content)
                await self._store.finish(context, content, usage)
                return
            if judgment.decision == "retry":
                feedback = LLMMessage(role="reviewer", content=judgment.model_dump_json())
                messages.append(feedback)
                await self._store.append_message(context, feedback, "judge.reviewed")
                await self._store.checkpoint(
                    context,
                    iteration,
                    "judge_retry",
                    usage,
                    budget_tool_calls=budget_tool_calls,
                )
                continue
            if "turn_budget_exhausted" not in judgment.issues:
                raise RuntimeError(judgment.feedback)
            budget_reason = "model_turns"
            await self._enter_budget_grace(
                context,
                messages,
                last_work_iteration,
                usage,
                budget_tool_calls,
                budget_reason,
            )

    async def _complete_turn(
        self,
        context: LoopContext,
        messages: list[LLMMessage],
        definitions: list[ToolDefinition],
        usage: dict[str, int],
        iteration: int,
    ) -> tuple[LLMResponse, UUID]:
        request = LLMRequest(
            model=context.colony.model,
            messages=messages,
            tools=definitions,
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
        usage["input_tokens"] += response.input_tokens
        usage["output_tokens"] += response.output_tokens
        self._logger.info(
            "agent_turn_usage",
            session_id=str(context.session.id),
            actor_type=context.session.actor_type,
            model=response.model,
            iteration=iteration,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            requested_tool_calls=len(response.tool_calls),
            total_input_tokens=usage["input_tokens"],
            total_output_tokens=usage["output_tokens"],
            total_tool_calls=usage["tool_calls"],
        )
        return response, message_id

    async def _execute_tool_calls(
        self,
        context: LoopContext,
        tool_calls: list[ToolCall],
        definitions: list[ToolDefinition],
        *,
        in_grace: bool,
        remaining_budget: int,
    ) -> tuple[list[ToolExecutionResult], int, bool]:
        allowed_names = {definition.name for definition in definitions}
        executable_indices: list[int] = []
        results: list[ToolExecutionResult | None] = [None] * len(tool_calls)
        remaining = max(0, remaining_budget)
        budget_exhausted = False

        for index, tool_call in enumerate(tool_calls):
            if in_grace and tool_call.name not in allowed_names:
                results[index] = ToolExecutionResult(
                    {
                        "error": {
                            "code": "TOOL_NOT_ALLOWED_IN_GRACE",
                            "message": "预算收尾阶段只允许保存进度和向 Queen 汇报。",
                        }
                    }
                )
            elif not in_grace and len(executable_indices) >= remaining:
                budget_exhausted = True
                results[index] = ToolExecutionResult(
                    {
                        "error": {
                            "code": "TOOL_BUDGET_EXHAUSTED",
                            "message": "工具调用预算已耗尽，本次调用未执行。",
                        }
                    }
                )
            else:
                executable_indices.append(index)

        executed = await asyncio.gather(
            *(self._tools.execute(context, tool_calls[index]) for index in executable_indices)
        )
        for index, result in zip(executable_indices, executed, strict=True):
            results[index] = result
        if any(result is None for result in results):
            raise RuntimeError("Tool result assembly is incomplete")
        return (
            [result for result in results if result is not None],
            len(executed),
            budget_exhausted,
        )

    async def _enter_budget_grace(
        self,
        context: LoopContext,
        messages: list[LLMMessage],
        iteration: int,
        usage: dict[str, int],
        budget_tool_calls: int,
        reason: BudgetReason,
    ) -> None:
        reminder = LLMMessage(role="system", content=self._budget_reminder(context, reason))
        messages.append(reminder)
        await self._store.checkpoint(
            context,
            iteration,
            "budget_grace",
            usage,
            budget_tool_calls=budget_tool_calls,
            budget_reason=reason,
            grace_turn=0,
        )
        self._logger.info(
            "agent_budget_grace_started",
            session_id=str(context.session.id),
            actor_type=context.session.actor_type,
            reason=reason,
            iteration=iteration,
            budget_tool_calls=budget_tool_calls,
        )

    async def _finish_budget_exhausted(
        self,
        context: LoopContext,
        reason: BudgetReason,
        usage: dict[str, int],
        budget_tool_calls: int,
        grace_turn: int,
    ) -> None:
        content = self._budget_fallback(context, reason)
        await self._store.append_message(
            context,
            LLMMessage(role="assistant", content=content),
            "message.completed",
        )
        await self._tools.finalize_budget_exhausted(context, content, reason)
        await self._store.finish(context, content, usage)
        self._log_budget_completion(
            context,
            reason,
            budget_tool_calls,
            grace_turn,
            fallback=True,
        )

    def _log_budget_completion(
        self,
        context: LoopContext,
        reason: BudgetReason,
        budget_tool_calls: int,
        grace_turn: int,
        *,
        fallback: bool,
    ) -> None:
        self._logger.info(
            "agent_budget_grace_completed",
            session_id=str(context.session.id),
            actor_type=context.session.actor_type,
            reason=reason,
            budget_tool_calls=budget_tool_calls,
            grace_turn=grace_turn,
            fallback=fallback,
        )

    @staticmethod
    def _budget_reminder(context: LoopContext, reason: BudgetReason) -> str:
        trigger = "模型轮次" if reason == "model_turns" else "工具调用"
        if context.session.actor_type == "queen":
            return (
                f"本轮{trigger}预算已经耗尽。这是最后的收尾回合，不得再调用工具。"
                "请依据已有消息和 Worker 报告，向用户说明当前结果与未完成事项。"
            )
        return (
            f"本次任务的{trigger}预算已经耗尽，现已进入收尾阶段。"
            "只能调用 report_to_parent、tracker_upsert 或 task_update；"
            "请保存必要进度，并立即向 Queen 汇报 success、partial 或 failed。"
        )

    @staticmethod
    def _budget_fallback(context: LoopContext, reason: BudgetReason) -> str:
        trigger = "模型轮次" if reason == "model_turns" else "工具调用"
        if context.session.actor_type == "queen":
            return f"本轮{trigger}预算已耗尽，当前进度已经保留。你可以继续补充要求。"
        return f"Worker 的{trigger}预算已耗尽，未能完成全部任务；已有进度和 Tracker 数据已保留。"

    @staticmethod
    def _restored_budget_reason(session: SessionRead) -> BudgetReason | None:
        if session.cursor.get("phase") != "budget_grace":
            return None
        reason = session.cursor.get("budget_reason")
        if reason == "model_turns":
            return "model_turns"
        if reason == "tool_calls":
            return "tool_calls"
        return None

    @staticmethod
    def _initial_budget_tool_calls(
        session: SessionRead,
        usage: dict[str, int],
    ) -> int:
        restored = session.cursor.get("budget_tool_calls")
        if isinstance(restored, int) and restored >= 0:
            return restored
        return usage["tool_calls"] if session.actor_type == "worker" else 0

    @staticmethod
    def _non_negative_int(value: JsonValue | None) -> int:
        return value if isinstance(value, int) and value >= 0 else 0

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
    "BudgetReason",
    "LoopContext",
    "ToolExecutionResult",
]
