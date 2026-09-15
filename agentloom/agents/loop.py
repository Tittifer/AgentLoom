"""The single multi-turn execution primitive used by queens and workers."""

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID, uuid4

import structlog
from pydantic import JsonValue

from agentloom.agents.judge import JudgePipeline
from agentloom.colony.schemas import (
    DEFAULT_WORKER_GRACE_ITERATIONS,
    DEFAULT_WORKER_MAX_ITERATIONS,
    DEFAULT_WORKER_TOOL_CALL_BUDGET,
    DEFAULT_WORKER_TOOL_CALL_LIFETIME_BUDGET,
    WORKER_TOOL_CALL_HARD_MULTIPLE,
    AgentExecutionRead,
    ColonyRead,
    MessageRead,
    QueenRead,
)
from agentloom.llm.base import (
    LLMContextLengthError,
    LLMMessage,
    LLMProvider,
    LLMProviderError,
    LLMRequest,
    LLMResponse,
    LLMResponseError,
    ToolCall,
    ToolDefinition,
)

BudgetReason = Literal["model_turns", "tool_calls"]

GRACE_TERMINAL_TOOL_NAMES = frozenset({"report_to_parent", "tracker_upsert", "task_update"})
DEFAULT_QUEEN_GRACE_TURNS = 1
MAX_LLM_TRANSIENT_RETRIES = 5
LLM_RETRY_BACKOFF_BASE_SECONDS = 2.0
LLM_RETRY_MAX_DELAY_SECONDS = 60.0
CAPACITY_RETRY_MAX_SECONDS = 600.0


@dataclass(frozen=True)
class LoopContext:
    # `session` is the loop's private execution state. A worker execution is
    # deliberately not exposed or persisted as a user Session.
    session: AgentExecutionRead
    colony: ColonyRead | None
    messages: list[LLMMessage]
    model: str = ""
    queen: QueenRead | None = None
    recalled_memory: str = ""


@dataclass(frozen=True)
class ToolExecutionResult:
    value: JsonValue
    terminate: bool = False


@dataclass(frozen=True)
class _InjectedMessage:
    message: LLMMessage
    persist: bool


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
        snapshot: str,
    ) -> None: ...

    async def cancel_message_stream(
        self,
        context: LoopContext,
        message_id: UUID,
    ) -> None: ...

    async def record_llm_retry(
        self,
        context: LoopContext,
        error: LLMProviderError,
        attempt: int,
        max_retries: int | None,
        delay_seconds: float,
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
        inner_turn: int = 0,
        turn_tool_calls: int = 0,
    ) -> None: ...

    async def finish(
        self,
        context: LoopContext,
        content: str,
        usage: dict[str, int],
    ) -> None: ...

    async def fail(self, context: LoopContext, error: Exception) -> None: ...


class AgentToolExecutor(Protocol):
    def definitions(self, context: LoopContext) -> list[ToolDefinition]: ...

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


class AgentLoopObserver(Protocol):
    async def on_turn_completed(
        self,
        context: LoopContext,
        response: LLMResponse,
        provider: LLMProvider,
    ) -> None: ...


class AgentContextManager(Protocol):
    async def compact(
        self,
        context: LoopContext,
        messages: list[LLMMessage],
        tools: list[ToolDefinition],
        provider: LLMProvider,
        *,
        force: bool,
    ) -> list[LLMMessage]: ...


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
        observer: AgentLoopObserver | None = None,
        context_manager: AgentContextManager | None = None,
    ) -> None:
        self._store = store
        self._provider = provider
        self._tools = tools
        self._judge = judge
        self._default_max_turns = default_max_turns
        self._timeout_seconds = timeout_seconds
        self._observer = observer
        self._context_manager = context_manager
        self._injected_messages: asyncio.Queue[_InjectedMessage] = asyncio.Queue()
        self._logger = structlog.get_logger(__name__)

    async def inject_user_message(self, content: str) -> None:
        """Queue one runtime message for the next model-turn boundary."""

        normalized = content.strip()
        if not normalized:
            raise ValueError("Injected message must not be empty")
        await self._injected_messages.put(
            _InjectedMessage(LLMMessage(role="user", content=normalized), persist=True)
        )

    async def inject_recalled_memory(self, content: str) -> None:
        """Queue refreshed memory for the active Queen without exposing it to users."""

        normalized = content.strip()
        if not normalized:
            return
        await self._injected_messages.put(
            _InjectedMessage(self._recalled_memory_message(normalized), persist=False)
        )

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
        if context.recalled_memory:
            reminder = self._recalled_memory_message(context.recalled_memory)
            insert_at = max(
                (index for index, message in enumerate(messages) if message.role == "user"),
                default=len(messages),
            )
            messages.insert(insert_at, reminder)
        usage = self._initial_usage(context.session)
        if context.session.actor_type == "worker":
            await self._run_worker(context, messages, usage)
            return
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
            else DEFAULT_QUEEN_GRACE_TURNS
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
            await self._drain_injected_messages(context, messages)
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
            definitions = self._tools.definitions(context)
            if in_grace:
                definitions = []
            if self._context_manager is not None:
                messages = await self._context_manager.compact(
                    context, messages, definitions, self._provider, force=False
                )
            try:
                response, message_id = await self._complete_turn_with_retry(
                    context,
                    messages,
                    definitions,
                    usage,
                    iteration,
                )
            except LLMContextLengthError:
                if self._context_manager is None:
                    raise
                messages = await self._context_manager.compact(
                    context, messages, definitions, self._provider, force=True
                )
                response, message_id = await self._complete_turn_with_retry(
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
            if self._observer is not None:
                await self._observer.on_turn_completed(context, response, self._provider)

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

    async def _run_worker(
        self,
        context: LoopContext,
        messages: list[LLMMessage],
        usage: dict[str, int],
    ) -> None:
        """Run a Worker with Hive-style outer iterations and an inner tool loop."""

        budget = context.session.budget
        max_iterations = self._positive_int(
            budget.get("max_iterations"), DEFAULT_WORKER_MAX_ITERATIONS
        )
        grace_iterations = self._non_negative_int_or_default(
            budget.get("grace_iterations"), DEFAULT_WORKER_GRACE_ITERATIONS
        )
        tool_call_budget = self._non_negative_int_or_default(
            budget.get("tool_call_budget"), DEFAULT_WORKER_TOOL_CALL_BUDGET
        )
        hard_multiple = self._positive_int(
            budget.get("tool_call_hard_multiple"), WORKER_TOOL_CALL_HARD_MULTIPLE
        )
        lifetime_budget = self._non_negative_int_or_default(
            budget.get("tool_call_lifetime_budget"),
            DEFAULT_WORKER_TOOL_CALL_LIFETIME_BUDGET,
        )
        hard_limit = tool_call_budget * hard_multiple if tool_call_budget else 0
        cursor = context.session.cursor
        phase = cursor.get("phase")
        budget_tool_calls = self._initial_budget_tool_calls(context.session, usage)
        budget_reason = self._restored_budget_reason(context.session)
        grace_turn = (
            self._non_negative_int(cursor.get("grace_turn")) if budget_reason is not None else 0
        )
        if phase == "nested_after_tools":
            iteration = max(1, self._non_negative_int(cursor.get("iteration")))
            inner_turn = self._non_negative_int(cursor.get("inner_turn"))
            turn_tool_calls = self._non_negative_int(cursor.get("turn_tool_calls"))
        else:
            iteration = self._non_negative_int(cursor.get("iteration")) + 1
            inner_turn = 0
            turn_tool_calls = 0

        if phase == "nested_after_tools" and hard_limit and turn_tool_calls >= hard_limit:
            iteration += 1
            inner_turn = 0
            turn_tool_calls = 0
        elif (
            phase == "nested_after_tools"
            and tool_call_budget
            and turn_tool_calls >= tool_call_budget
            and turn_tool_calls < hard_limit
        ):
            messages.append(
                LLMMessage(
                    role="system",
                    content=self._worker_tool_budget_reminder(turn_tool_calls, hard_limit),
                )
            )

        if budget_reason is not None:
            messages.append(
                LLMMessage(role="system", content=self._budget_reminder(context, budget_reason))
            )

        while True:
            await self._drain_injected_messages(context, messages)
            if budget_reason is None:
                if iteration > max_iterations:
                    budget_reason = "model_turns"
                elif lifetime_budget and budget_tool_calls >= lifetime_budget:
                    budget_reason = "tool_calls"
                if budget_reason is not None:
                    await self._enter_budget_grace(
                        context,
                        messages,
                        max(0, iteration - 1),
                        usage,
                        budget_tool_calls,
                        budget_reason,
                    )

            if budget_reason is not None and grace_turn >= grace_iterations:
                await self._finish_budget_exhausted(
                    context,
                    budget_reason,
                    usage,
                    budget_tool_calls,
                    grace_turn,
                )
                return

            in_grace = budget_reason is not None
            definitions = self._tools.definitions(context)
            if in_grace:
                definitions = [
                    definition
                    for definition in definitions
                    if definition.name in GRACE_TERMINAL_TOOL_NAMES
                ]
            if self._context_manager is not None:
                messages = await self._context_manager.compact(
                    context, messages, definitions, self._provider, force=False
                )
            try:
                response, message_id = await self._complete_turn_with_retry(
                    context,
                    messages,
                    definitions,
                    usage,
                    iteration,
                )
            except LLMContextLengthError:
                if self._context_manager is None:
                    raise
                messages = await self._context_manager.compact(
                    context, messages, definitions, self._provider, force=True
                )
                response, message_id = await self._complete_turn_with_retry(
                    context,
                    messages,
                    definitions,
                    usage,
                    iteration,
                )

            inner_turn += 1
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
            if self._observer is not None:
                await self._observer.on_turn_completed(context, response, self._provider)

            if not response.tool_calls:
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
                        max(0, iteration - 1),
                        "budget_grace",
                        usage,
                        budget_tool_calls=budget_tool_calls,
                        budget_reason=budget_reason,
                        grace_turn=grace_turn,
                        inner_turn=inner_turn,
                        turn_tool_calls=turn_tool_calls,
                    )
                    inner_turn = 0
                    turn_tool_calls = 0
                    continue

                judgment = self._judge.review(
                    content,
                    iteration=iteration,
                    max_turns=max_iterations,
                )
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
                        "nested_iteration_complete",
                        usage,
                        budget_tool_calls=budget_tool_calls,
                    )
                    iteration += 1
                    inner_turn = 0
                    turn_tool_calls = 0
                    continue
                if "turn_budget_exhausted" not in judgment.issues:
                    raise RuntimeError(judgment.feedback)
                budget_reason = "model_turns"
                await self._enter_budget_grace(
                    context,
                    messages,
                    iteration,
                    usage,
                    budget_tool_calls,
                    budget_reason,
                )
                iteration += 1
                inner_turn = 0
                turn_tool_calls = 0
                continue

            remaining_hard = (
                max(0, hard_limit - turn_tool_calls) if hard_limit else len(response.tool_calls)
            )
            remaining_lifetime = (
                max(0, lifetime_budget - budget_tool_calls)
                if lifetime_budget and not in_grace
                else len(response.tool_calls)
            )
            remaining_budget = min(remaining_hard, remaining_lifetime)
            results, executed_count, hard_exhausted = await self._execute_tool_calls(
                context,
                response.tool_calls,
                definitions,
                in_grace=in_grace,
                remaining_budget=remaining_budget,
                enforce_budget_in_grace=True,
                exhaustion_code="TOOL_CALL_DEFERRED",
                exhaustion_message=(
                    "当前 Worker 可用的工具调用额度已达到上限；本次调用未执行，"
                    "请基于已有结果收敛或在下一工作迭代继续。"
                ),
            )
            usage["tool_calls"] += executed_count
            previous_turn_tool_calls = turn_tool_calls
            turn_tool_calls += executed_count
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

            self._logger.info(
                "agent_tool_usage",
                session_id=str(context.session.id),
                actor_type=context.session.actor_type,
                iteration=iteration,
                inner_turn=inner_turn,
                in_grace=in_grace,
                requested_tool_calls=len(response.tool_calls),
                executed_tool_calls=executed_count,
                skipped_tool_calls=len(response.tool_calls) - executed_count,
                turn_tool_calls=turn_tool_calls,
                work_budget_tool_calls=budget_tool_calls,
                total_tool_calls=usage["tool_calls"],
            )
            if any(result.terminate for result in results):
                await self._store.finish(context, content, usage)
                return

            if (
                tool_call_budget
                and turn_tool_calls < hard_limit
                and turn_tool_calls // tool_call_budget
                > previous_turn_tool_calls // tool_call_budget
            ):
                messages.append(
                    LLMMessage(
                        role="system",
                        content=self._worker_tool_budget_reminder(
                            turn_tool_calls,
                            hard_limit,
                        ),
                    )
                )

            await self._store.checkpoint(
                context,
                iteration,
                "nested_after_tools",
                usage,
                budget_tool_calls=budget_tool_calls,
                budget_reason=budget_reason,
                grace_turn=grace_turn,
                inner_turn=inner_turn,
                turn_tool_calls=turn_tool_calls,
            )

            lifetime_exhausted = (
                not in_grace and lifetime_budget > 0 and budget_tool_calls >= lifetime_budget
            )
            iteration_hard_exhausted = hard_limit > 0 and (
                hard_exhausted or turn_tool_calls >= hard_limit
            )
            if lifetime_exhausted:
                budget_reason = "tool_calls"
                await self._enter_budget_grace(
                    context,
                    messages,
                    iteration,
                    usage,
                    budget_tool_calls,
                    budget_reason,
                )
                iteration += 1
                inner_turn = 0
                turn_tool_calls = 0
                continue
            if iteration_hard_exhausted:
                if in_grace:
                    grace_turn += 1
                await self._store.checkpoint(
                    context,
                    iteration,
                    "budget_grace" if in_grace else "nested_iteration_complete",
                    usage,
                    budget_tool_calls=budget_tool_calls,
                    budget_reason=budget_reason,
                    grace_turn=grace_turn,
                )
                if not in_grace:
                    iteration += 1
                inner_turn = 0
                turn_tool_calls = 0
                continue

    async def _drain_injected_messages(
        self,
        context: LoopContext,
        messages: list[LLMMessage],
    ) -> None:
        injected = 0
        while True:
            try:
                injected_message = self._injected_messages.get_nowait()
            except asyncio.QueueEmpty:
                break
            message = injected_message.message
            messages.append(message)
            if injected_message.persist:
                await self._store.append_message(context, message, "message.injected")
            injected += 1
        if injected:
            self._logger.info(
                "agent_messages_injected",
                session_id=str(context.session.id),
                actor_type=context.session.actor_type,
                count=injected,
            )

    @staticmethod
    def _recalled_memory_message(content: str) -> LLMMessage:
        return LLMMessage(
            role="system",
            content=(
                "<system-reminder>\n以下是与用户本轮请求相关的长期记忆。"
                "这些信息可能已经过时，请结合当前上下文核实。\n\n"
                f"{content}\n</system-reminder>"
            ),
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
            model=context.model,
            messages=messages,
            tools=definitions,
            timeout_seconds=self._timeout_seconds,
        )
        message_id = uuid4()
        response = None
        stream_visible = False
        visible_snapshot = ""
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
                    visible_snapshot += chunk.content_delta
                    await self._store.publish_message_delta(
                        context,
                        message_id,
                        chunk.content_delta,
                        visible_snapshot,
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
        usage["last_input_tokens"] = response.input_tokens
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

    async def _complete_turn_with_retry(
        self,
        context: LoopContext,
        messages: list[LLMMessage],
        definitions: list[ToolDefinition],
        usage: dict[str, int],
        iteration: int,
    ) -> tuple[LLMResponse, UUID]:
        transient_retries = 0
        capacity_retries = 0
        capacity_started_at: float | None = None

        while True:
            try:
                return await self._complete_turn(
                    context,
                    messages,
                    definitions,
                    usage,
                    iteration,
                )
            except LLMProviderError as error:
                if not error.retryable or error.category == "context_length":
                    raise

                if error.category == "capacity":
                    if capacity_started_at is None:
                        capacity_started_at = time.monotonic()
                    remaining_seconds = CAPACITY_RETRY_MAX_SECONDS - (
                        time.monotonic() - capacity_started_at
                    )
                    if remaining_seconds <= 0:
                        raise
                    capacity_retries += 1
                    attempt = capacity_retries
                    max_retries = None
                    delay_seconds = min(
                        self._llm_retry_delay(error, attempt),
                        remaining_seconds,
                    )
                else:
                    if transient_retries >= MAX_LLM_TRANSIENT_RETRIES:
                        raise
                    transient_retries += 1
                    attempt = transient_retries
                    max_retries = MAX_LLM_TRANSIENT_RETRIES
                    delay_seconds = self._llm_retry_delay(error, attempt)

                await self._store.record_llm_retry(
                    context,
                    error,
                    attempt,
                    max_retries,
                    delay_seconds,
                )
                self._logger.warning(
                    "llm_request_retrying",
                    session_id=str(context.session.id),
                    actor_type=context.session.actor_type,
                    category=error.category,
                    status_code=error.status_code,
                    attempt=attempt,
                    max_retries=max_retries,
                    delay_seconds=delay_seconds,
                )
                await asyncio.sleep(delay_seconds)

    @staticmethod
    def _llm_retry_delay(error: LLMProviderError, attempt: int) -> float:
        if error.retry_after_seconds is not None:
            return min(
                max(0.0, error.retry_after_seconds),
                LLM_RETRY_MAX_DELAY_SECONDS,
            )
        return min(
            LLM_RETRY_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)),
            LLM_RETRY_MAX_DELAY_SECONDS,
        )

    async def _execute_tool_calls(
        self,
        context: LoopContext,
        tool_calls: list[ToolCall],
        definitions: list[ToolDefinition],
        *,
        in_grace: bool,
        remaining_budget: int,
        enforce_budget_in_grace: bool = False,
        exhaustion_code: str = "TOOL_BUDGET_EXHAUSTED",
        exhaustion_message: str = "工具调用预算已耗尽，本次调用未执行。",
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
            elif (not in_grace or enforce_budget_in_grace) and len(executable_indices) >= remaining:
                budget_exhausted = True
                results[index] = ToolExecutionResult(
                    {
                        "error": {
                            "code": exhaustion_code,
                            "message": exhaustion_message,
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
    def _restored_budget_reason(session: AgentExecutionRead) -> BudgetReason | None:
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
        session: AgentExecutionRead,
        usage: dict[str, int],
    ) -> int:
        restored = session.cursor.get("budget_tool_calls")
        if isinstance(restored, int) and restored >= 0:
            return restored
        return usage["tool_calls"] if session.actor_type == "worker" else 0

    @staticmethod
    def _positive_int(value: JsonValue | None, default: int) -> int:
        return value if isinstance(value, int) and value > 0 else default

    @staticmethod
    def _non_negative_int_or_default(value: JsonValue | None, default: int) -> int:
        return value if isinstance(value, int) and value >= 0 else default

    @staticmethod
    def _worker_tool_budget_reminder(tool_calls: int, hard_limit: int) -> str:
        return (
            f"本工作迭代已调用 {tool_calls} 次工具，硬上限为 {hard_limit} 次。"
            "请复用已有结果、减少重复调用，并尽快写入 Tracker 后向 Queen 汇报。"
        )

    @staticmethod
    def _non_negative_int(value: JsonValue | None) -> int:
        return value if isinstance(value, int) and value >= 0 else 0

    @staticmethod
    def _system_message(context: LoopContext) -> LLMMessage:
        if context.session.actor_type == "queen":
            if context.session.mode == "dm":
                runtime_prompt = (
                    "你是 AgentLoom 的独立 Queen，先直接帮助用户验证工作方法。"
                    "你当前没有 Colony、Tracker 或 Worker；不得假装已经派生 Worker。"
                    "只有当任务确实适合并行、周期性或长期运行时，才调用 suggest_colony 提出建议；"
                    "该工具只请求用户确认，不会直接创建 Colony。最终回复必须使用中文。"
                )
            else:
                runtime_prompt = (
                    "你是 AgentLoom Colony 的 Queen。持续与用户协作，维护计划和共享 Tracker。"
                    "Tracker 必须使用真实业务表：每个工作单元占一行，并有可判定完成的字段。"
                    "先用 tracker_sql 建表和写入初始行，再用 tracker_register_writable 限定 Worker"
                    "可写列与键；复杂批次先派一个 Worker 验证读写闭环，再扩展并行。"
                    "当任务可并行时先用 task_create 建立任务，再调用 run_worker；"
                    "run_worker 的每个 tasks[].data.task_id 必须使用对应任务 UUID。"
                    "Worker 报告会作为用户消息回到当前会话。"
                    "不要虚构工具结果，最终回复必须使用中文。"
                )
            identity_prompt = context.queen.system_prompt if context.queen is not None else ""
            content = (
                f"{identity_prompt}\n\n{runtime_prompt}" if identity_prompt else runtime_prompt
            )
        else:
            content = (
                "你是 Queen 派生的临时 Worker。只完成注入的单一任务，不得派生其他 Worker，"
                "不能等待用户回答。先用 tracker_query 读取自己的业务行，只通过 tracker_upsert"
                "更新已登记列；Tracker 只保存短结构化字段，完整说明通过 report_to_parent 汇报。"
                f"任务：{json.dumps(context.session.task, ensure_ascii=False)}"
            )
        return LLMMessage(role="system", content=content)

    @staticmethod
    def _initial_usage(session: AgentExecutionRead) -> dict[str, int]:
        result: dict[str, int] = {}
        for key in ("input_tokens", "output_tokens", "tool_calls", "last_input_tokens"):
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
    "AgentLoopObserver",
    "AgentContextManager",
    "AgentToolExecutor",
    "BudgetReason",
    "LoopContext",
    "ToolExecutionResult",
]
