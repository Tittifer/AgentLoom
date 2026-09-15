"""Persistent Queen/Worker Colony runtime and lifecycle commands."""

import asyncio
import json
import sqlite3
from collections.abc import Coroutine
from typing import Literal
from uuid import UUID, uuid4

import structlog
from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError

from agentloom.agents.judge import JudgePipeline
from agentloom.agents.loop import (
    AgentContextManager,
    AgentLoop,
    AgentLoopStore,
    BudgetReason,
    LoopContext,
    ToolExecutionResult,
)
from agentloom.colony.message_safety import sanitize_text
from agentloom.colony.notifier import ColonyEventNotifier
from agentloom.colony.schemas import (
    DEFAULT_WORKER_MAX_ITERATIONS,
    ActorType,
    ColonyCreate,
    ColonyEventRead,
    ColonyForkCreate,
    ColonyRead,
    ColonySnapshot,
    ColonySuggestion,
    MessageRead,
    QueenCreate,
    QueenRead,
    SessionCreate,
    SessionRead,
    TaskItemCreate,
    TaskItemRead,
    TrackerChangesRead,
    TrackerRowsRead,
    TrackerTableRead,
    TrackerUpsert,
    WorkerRead,
    WorkerReport,
    WorkerTask,
)
from agentloom.config import Settings
from agentloom.context.compaction import ContextCompactor
from agentloom.context.estimator import estimate_context_tokens
from agentloom.context.schemas import CompactionCheckpoint, ContextPolicy
from agentloom.llm.base import (
    LLMMessage,
    LLMProvider,
    LLMProviderError,
    ToolCall,
    ToolDefinition,
)
from agentloom.llm.factory import create_llm_provider
from agentloom.memory.coordinator import MemoryCoordinator
from agentloom.memory.store import LocalMemoryStore
from agentloom.runtime.states import SessionStatus, TaskItemStatus, WorkerStatus
from agentloom.sessions import SessionManager
from agentloom.storage import LocalColonyStore, TrackerPermissionError
from agentloom.storage.base import utc_now
from agentloom.tools.base import ToolContext, ToolError
from agentloom.tools.mcp.manager import MCPManager
from agentloom.tools.registry import ToolRegistry
from agentloom.user_settings import UserLLMRuntimeConfig, UserSettingsRead, UserSettingsUpdate


class ColonyNotFoundError(LookupError):
    """Raised when a Colony command targets an unknown identifier."""


class SessionNotFoundError(LookupError):
    """Raised when a command targets an unknown agent session."""


class SessionConflictError(ValueError):
    """Raised when a session cannot accept the requested transition."""


class QueenNotFoundError(LookupError):
    """Raised when a Queen identity does not exist."""


class LLMSettingsNotConfiguredError(RuntimeError):
    """Raised when an operation requires missing global LLM settings."""


UNTITLED_COLONY_NAME = "新会话"
DEFAULT_WORKER_SOFT_TIMEOUT_SECONDS = 600
WORKER_HARD_TIMEOUT_CAP_SECONDS = 3600
WORKER_HARD_TIMEOUT_EXTRA_SECONDS = 600
WORKER_MIN_TIMEOUT_GRACE_SECONDS = 60
WORKER_STOP_TIMEOUT_SECONDS = 10
ACTIVE_WORKER_STATUSES = {
    WorkerStatus.QUEUED,
    WorkerStatus.RUNNING,
    WorkerStatus.REPORTING,
}


def worker_hard_timeout_seconds(soft_timeout_seconds: float) -> float:
    """Derive Hive-compatible hard timeout from a Worker's soft timeout."""

    hard_timeout = min(
        float(WORKER_HARD_TIMEOUT_CAP_SECONDS),
        max(
            soft_timeout_seconds * 4,
            soft_timeout_seconds + WORKER_HARD_TIMEOUT_EXTRA_SECONDS,
        ),
    )
    return max(
        hard_timeout,
        soft_timeout_seconds + WORKER_MIN_TIMEOUT_GRACE_SECONDS,
    )


class ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RunWorkersInput(ToolInput):
    tasks: list[WorkerTask] = Field(min_length=1, max_length=100)
    timeout: int = Field(
        default=DEFAULT_WORKER_SOFT_TIMEOUT_SECONDS,
        ge=1,
        le=3600,
        description="触发 Worker 收尾提醒的软超时秒数",
    )
    max_iterations: int | None = Field(
        default=None,
        ge=1,
        le=1000,
        description="外层工作迭代上限；默认 3，工具往返不会消耗该次数",
    )
    grace_iterations: int | None = Field(
        default=None,
        ge=0,
        le=3,
        description="预算耗尽后的收尾迭代数；默认 1",
    )
    tool_call_budget: int | None = Field(
        default=None,
        ge=0,
        le=200,
        description="每个工作迭代的工具调用软阈值；默认 30，0 表示关闭该限制",
    )
    tool_call_lifetime_budget: int | None = Field(
        default=None,
        ge=0,
        le=2000,
        description="整个 Worker 生命周期的工具调用上限；默认 200，0 表示关闭该限制",
    )

    def budget_overrides(self) -> dict[str, int]:
        return {
            key: value
            for key, value in {
                "max_iterations": self.max_iterations,
                "grace_iterations": self.grace_iterations,
                "tool_call_budget": self.tool_call_budget,
                "tool_call_lifetime_budget": self.tool_call_lifetime_budget,
            }.items()
            if value is not None
        }


class ReportInput(ToolInput):
    status: Literal["success", "partial", "failed"]
    summary: str = Field(min_length=1)
    data: dict[str, JsonValue] = Field(default_factory=dict)


class TrackerQueryInput(ToolInput):
    sql: str = Field(min_length=1, max_length=100_000)
    row_cap: int = Field(default=1_000, ge=1, le=10_000)


class TrackerSQLInput(ToolInput):
    sql: str = Field(min_length=1, max_length=100_000)
    row_cap: int = Field(default=1_000, ge=1, le=10_000)


class TrackerRegisterWritableInput(ToolInput):
    table: str = Field(min_length=1, max_length=100)
    write_columns: list[str] = Field(min_length=1, max_length=200)
    key_columns: list[str] = Field(min_length=1, max_length=20)


class TaskUpdateInput(ToolInput):
    task_id: UUID
    status: Literal["pending", "in_progress", "completed", "blocked", "cancelled"]


class LoadToolResultInput(ToolInput):
    filename: str = Field(min_length=1, max_length=200)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=10_000, ge=1, le=20_000)


class SuggestColonyInput(ToolInput):
    suggested_name: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=2_000)
    goal: str = Field(min_length=1, max_length=4_000)
    handoff: str = Field(min_length=1, max_length=20_000)
    proposed_tasks: list[str] = Field(default_factory=list, max_length=100)


def normalize_message_history(messages: list[MessageRead]) -> tuple[list[LLMMessage], int]:
    """Drop orphan tool results and downgrade incomplete assistant tool-call groups."""

    normalized: list[LLMMessage] = []
    repaired_groups = 0
    index = 0
    while index < len(messages):
        item = messages[index]
        message = LLMMessage.model_validate(
            {
                "role": item.role,
                "content": item.content,
                "reasoning_content": item.reasoning_content,
                "tool_call_id": item.tool_call_id,
                "tool_calls": item.tool_calls,
            }
        )
        if message.role == "assistant" and message.tool_calls:
            tool_messages: list[LLMMessage] = []
            next_index = index + 1
            while next_index < len(messages) and messages[next_index].role == "tool":
                tool_item = messages[next_index]
                tool_messages.append(
                    LLMMessage.model_validate(
                        {
                            "role": tool_item.role,
                            "content": tool_item.content,
                            "reasoning_content": tool_item.reasoning_content,
                            "tool_call_id": tool_item.tool_call_id,
                            "tool_calls": tool_item.tool_calls,
                        }
                    )
                )
                next_index += 1
            expected_ids = {call.id for call in message.tool_calls}
            response_ids = {tool.tool_call_id for tool in tool_messages}
            if len(tool_messages) == len(expected_ids) and response_ids == expected_ids:
                normalized.extend([message, *tool_messages])
            else:
                repaired_groups += 1
                if message.content:
                    normalized.append(message.model_copy(update={"tool_calls": []}))
            index = next_index
            continue
        if message.role == "tool":
            repaired_groups += 1
        else:
            normalized.append(message)
        index += 1
    return normalized, repaired_groups


def messages_for_checkpoint(
    messages: list[MessageRead], checkpoint: CompactionCheckpoint | None
) -> list[MessageRead]:
    if checkpoint is None:
        return messages
    preserved = set(checkpoint.preserved_sequences)
    return [
        message
        for message in messages
        if message.sequence in preserved or message.sequence > checkpoint.through_sequence
    ]


def _worker_status_context(
    workers: list[WorkerRead],
    messages: list[MessageRead],
) -> LLMMessage | None:
    """Build transient, authoritative Worker progress for a Queen model turn."""

    if not workers:
        return None
    reported_ids = {
        worker_id
        for message in messages
        if isinstance((worker_id := message.metadata.get("worker_run_id")), str)
    }
    pending = [worker for worker in workers if str(worker.id) not in reported_ids]
    terminal_statuses = {
        WorkerStatus.COMPLETED,
        WorkerStatus.PARTIAL,
        WorkerStatus.FAILED,
        WorkerStatus.TIMED_OUT,
        WorkerStatus.CANCELLED,
    }
    all_workers_terminal = all(worker.status in terminal_statuses for worker in workers)
    if not pending:
        instruction = "所有 Worker 报告均已收到。立即综合全部报告完成最终答复，不得声称仍在等待。"
    elif all_workers_terminal:
        instruction = (
            "所有 Worker 均已结束，不会再有新报告。立即使用现有报告完成最终答复，"
            "并明确说明无报告的失败项。"
        )
    else:
        instruction = "仍有 Worker 尚未报告；只可等待下列未报告项，不得把已报告项说成未完成。"
    payload = {
        "total_workers": len(workers),
        "received_reports": len(workers) - len(pending),
        "pending_workers": [
            {"worker_id": str(worker.id), "task": worker.task, "status": worker.status}
            for worker in pending
        ],
        "instruction": instruction,
    }
    return LLMMessage(
        role="system",
        content="[WORKER_STATUS]\n" + json.dumps(payload, ensure_ascii=False),
    )


class FileAgentLoopStore(AgentLoopStore):
    """Persist AgentLoop messages, checkpoints, and events locally."""

    def __init__(
        self,
        store: LocalColonyStore,
        notifier: ColonyEventNotifier,
        memory: MemoryCoordinator | None = None,
    ) -> None:
        self._store = store
        self._notifier = notifier
        self._memory = memory
        self._logger = structlog.get_logger(__name__)

    async def load(self, session_id: UUID) -> LoopContext | None:
        execution = await self._store.get_execution(session_id)
        if execution is None:
            return None
        colony = (
            await self._store.get(execution.colony_id) if execution.colony_id is not None else None
        )
        queen = await self._store.get_queen(execution.queen_id)
        llm = await self._store.get_user_llm_runtime_config()
        messages = await self._store.list_messages(session_id)
        if queen is None or messages is None:
            return None
        if execution.mode == "colony" and colony is None:
            return None
        compaction = await self._store.get_compaction_checkpoint(session_id)
        model_messages = [
            message for message in messages if not bool(message.metadata.get("exclude_from_model"))
        ]
        normalized, repaired_groups = normalize_message_history(
            messages_for_checkpoint(model_messages, compaction)
        )
        if compaction is not None:
            normalized.insert(
                0,
                LLMMessage(
                    role="user",
                    content="[CONTEXT_COMPACTION]\n" + compaction.summary,
                ),
            )
        if execution.actor_type == "queen" and execution.colony_id is not None:
            status_context = _worker_status_context(
                await self._store.list_workers(execution.colony_id),
                messages,
            )
            if status_context is not None:
                normalized.append(status_context)
        if repaired_groups:
            self._logger.warning(
                "incomplete_tool_history_repaired",
                session_id=str(session_id),
                repaired_groups=repaired_groups,
            )
        effective_session = execution
        if llm is not None:
            effective_session = execution.model_copy(
                update={
                    "budget": {
                        **execution.budget,
                        "max_context_tokens": llm.max_context_tokens,
                    }
                }
            )
        return LoopContext(
            session=effective_session,
            colony=colony,
            messages=normalized,
            model=llm.model if llm is not None else "",
            queen=queen,
            recalled_memory=(
                self._memory.recalled_memory(session_id) if self._memory is not None else ""
            ),
        )

    async def mark_running(self, context: LoopContext) -> bool:
        current = await self._store.get_execution(context.session.id)
        if current is None:
            return False
        if current.actor_type == "queen" and current.status in {
            SessionStatus.FORKED,
            SessionStatus.COMPLETED,
            SessionStatus.FAILED,
            SessionStatus.CANCELLED,
        }:
            return False
        if current.actor_type == "worker" and current.status not in {
            WorkerStatus.QUEUED,
            WorkerStatus.RUNNING,
        }:
            return False
        await self._store.set_execution_status(current.id, SessionStatus.RUNNING)
        await self._store.append_session_event(
            current.id,
            "session.started",
            payload={"actor_type": current.actor_type},
        )
        await self._notifier.notify(self._stream_id(context))
        return True

    async def append_message(
        self,
        context: LoopContext,
        message: LLMMessage,
        event_type: str,
        message_id: UUID | None = None,
    ) -> MessageRead:
        saved = await self._store.append_message(
            context.session.id,
            message,
            message_id=message_id,
        )
        if saved is None:
            raise SessionNotFoundError(str(context.session.id))
        await self._store.append_session_event(
            context.session.id,
            event_type,
            payload={"message_id": str(saved.id), "role": saved.role},
        )
        await self._notifier.notify(self._stream_id(context))
        return saved

    async def publish_message_delta(
        self,
        context: LoopContext,
        message_id: UUID,
        delta: str,
        snapshot: str,
    ) -> None:
        if context.session.actor_type != "queen":
            return
        await self._notifier.publish(
            self._stream_id(context),
            "message.delta",
            {
                "colony_id": (
                    str(context.session.colony_id)
                    if context.session.colony_id is not None
                    else None
                ),
                "session_id": str(context.session.id),
                "message_id": str(message_id),
                "delta": delta,
                "snapshot": snapshot,
            },
        )

    async def cancel_message_stream(
        self,
        context: LoopContext,
        message_id: UUID,
    ) -> None:
        if context.session.actor_type != "queen":
            return
        await self._notifier.publish(
            self._stream_id(context),
            "message.stream.cancelled",
            {
                "colony_id": (
                    str(context.session.colony_id)
                    if context.session.colony_id is not None
                    else None
                ),
                "session_id": str(context.session.id),
                "message_id": str(message_id),
            },
        )

    async def record_llm_retry(
        self,
        context: LoopContext,
        error: LLMProviderError,
        attempt: int,
        max_retries: int | None,
        delay_seconds: float,
    ) -> None:
        await self._store.append_session_event(
            context.session.id,
            "llm.retrying",
            payload={
                "actor_type": context.session.actor_type,
                "category": error.category,
                "status_code": error.status_code,
                "attempt": attempt,
                "max_retries": max_retries,
                "delay_seconds": delay_seconds,
                "message": sanitize_text(str(error)),
            },
        )
        await self._notifier.notify(self._stream_id(context))

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
    ) -> None:
        cursor: dict[str, object] = {
            "iteration": iteration,
            "phase": phase,
            "budget_tool_calls": budget_tool_calls,
        }
        if budget_reason is not None:
            cursor["budget_reason"] = budget_reason
            cursor["grace_turn"] = grace_turn
        if phase.startswith("nested_") or inner_turn or turn_tool_calls:
            cursor["inner_turn"] = inner_turn
            cursor["turn_tool_calls"] = turn_tool_calls
        await self._store.set_execution_status(
            context.session.id,
            SessionStatus.RUNNING,
            cursor=cursor,
            usage=usage,
        )
        if phase == "budget_grace" and budget_reason is not None and grace_turn == 0:
            await self._store.append_session_event(
                context.session.id,
                "session.budget_grace_started",
                payload={
                    "actor_type": context.session.actor_type,
                    "reason": budget_reason,
                    "iteration": iteration,
                    "budget_tool_calls": budget_tool_calls,
                },
            )
            await self._notifier.notify(self._stream_id(context))

    async def finish(self, context: LoopContext, content: str, usage: dict[str, int]) -> None:
        del content
        current = await self._store.get_execution(context.session.id)
        if current is None:
            return
        if current.actor_type == "queen":
            await self._store.set_execution_status(
                current.id,
                SessionStatus.IDLE,
                cursor={"iteration": 0, "phase": "idle"},
                usage=usage,
            )
            await self._store.append_session_event(
                current.id,
                "session.idle",
                payload={"actor_type": "queen"},
            )
        else:
            await self._store.set_execution_status(
                current.id,
                current.status,
                cursor={"iteration": 0, "phase": "completed"},
                usage=usage,
            )
        await self._notifier.notify(self._stream_id(context))

    async def fail(self, context: LoopContext, error: Exception) -> None:
        safe_error = sanitize_text(str(error))
        self._logger.error(
            "agent_session_failed",
            session_id=str(context.session.id),
            actor_type=context.session.actor_type,
            error_type=type(error).__name__,
            error=safe_error,
        )
        llm_error = error if isinstance(error, LLMProviderError) else None
        worker = await self._store.get_worker(context.session.id)
        if worker is not None:
            saved = await self._store.finish_worker_if_active(
                context.session.id,
                WorkerStatus.FAILED,
                error={
                    "code": (
                        "LLM_RETRY_EXHAUSTED"
                        if llm_error is not None and llm_error.retryable
                        else (
                            f"LLM_{llm_error.category.upper()}"
                            if llm_error is not None and type(llm_error) is not LLMProviderError
                            else "AGENT_LOOP_FAILED"
                        )
                    ),
                    "message": safe_error,
                },
            )
            if saved is None:
                self._logger.info(
                    "agent_session_failure_ignored_terminal",
                    session_id=str(context.session.id),
                    worker_run_id=str(worker.id),
                )
                return
            worker = saved
        elif llm_error is not None:
            await self._park_queen_after_llm_error(context, llm_error, safe_error)
            return
        else:
            await self._store.set_execution_status(context.session.id, SessionStatus.FAILED)
        if llm_error is not None:
            await self._store.append_session_event(
                context.session.id,
                "llm.retry_exhausted",
                worker_run_id=worker.id if worker is not None else None,
                payload={
                    "actor_type": context.session.actor_type,
                    "category": llm_error.category,
                    "status_code": llm_error.status_code,
                    "retryable": llm_error.retryable,
                    "message": safe_error,
                },
            )
        await self._store.append_session_event(
            context.session.id,
            "session.failed",
            worker_run_id=worker.id if worker is not None else None,
            payload={"message": safe_error},
        )
        await self._notifier.notify(self._stream_id(context))

    async def _park_queen_after_llm_error(
        self,
        context: LoopContext,
        error: LLMProviderError,
        safe_error: str,
    ) -> None:
        await self._store.set_execution_status(
            context.session.id,
            SessionStatus.PARKED,
            park_reason="llm_error",
        )
        saved = await self._store.append_message(
            context.session.id,
            LLMMessage(
                role="assistant",
                content=(
                    f"模型调用失败：{safe_error}\n\n"
                    "请检查用户设置或模型服务状态，然后发送消息重试。"
                ),
            ),
            metadata={"kind": "llm_error", "exclude_from_model": True},
        )
        if saved is not None:
            await self._store.append_session_event(
                context.session.id,
                "message.completed",
                payload={"message_id": str(saved.id), "role": saved.role},
            )
        await self._store.append_session_event(
            context.session.id,
            "llm.retry_exhausted",
            payload={
                "actor_type": context.session.actor_type,
                "category": error.category,
                "status_code": error.status_code,
                "retryable": error.retryable,
                "message": safe_error,
            },
        )
        await self._store.append_session_event(
            context.session.id,
            "session.parked",
            payload={"actor_type": context.session.actor_type, "reason": "llm_error"},
        )
        await self._notifier.notify(self._stream_id(context))

    @staticmethod
    def _stream_id(context: LoopContext) -> UUID:
        return context.session.owner_session_id


class FileContextManager(AgentContextManager):
    """Compact one Session while preserving its complete user-visible transcript."""

    def __init__(
        self,
        store: LocalColonyStore,
        timeout_seconds: float,
        memory: MemoryCoordinator | None,
    ) -> None:
        self._store = store
        self._compactor = ContextCompactor(timeout_seconds)
        self._memory = memory
        self._logger = structlog.get_logger(__name__)

    async def compact(
        self,
        context: LoopContext,
        messages: list[LLMMessage],
        tools: list[ToolDefinition],
        provider: LLMProvider,
        *,
        force: bool,
    ) -> list[LLMMessage]:
        policy = ContextPolicy.from_mapping(context.session.budget)
        previous = await self._store.get_compaction_checkpoint(context.session.id)
        microcompacted = self._compactor.microcompact(messages)
        estimated_tokens = estimate_context_tokens(microcompacted, tools)
        last_actual = context.session.usage.get("last_input_tokens")
        tokens_before = max(
            estimated_tokens,
            (
                last_actual
                if previous is None and isinstance(last_actual, int) and last_actual >= 0
                else 0
            ),
        )
        if not force and tokens_before < policy.trigger_tokens:
            return microcompacted
        raw_messages = await self._store.list_messages(context.session.id)
        if not raw_messages:
            if force:
                raise RuntimeError("上下文超过模型限制，但没有足够的历史消息可压缩")
            return microcompacted
        active_raw = [
            message
            for message in raw_messages
            if previous is None or message.sequence > previous.through_sequence
        ]
        split = self._recent_start(active_raw)
        if split <= 0 and previous is None:
            if force:
                raise RuntimeError("上下文超过模型限制，但近期消息组无法安全拆分")
            return microcompacted
        old_messages = active_raw[:split]
        recent_messages = active_raw[split:]
        old_normalized, _ = normalize_message_history(old_messages)
        if previous is not None:
            old_normalized.insert(
                0,
                LLMMessage(
                    role="user",
                    content="[PREVIOUS_CONTEXT_COMPACTION]\n" + previous.summary,
                ),
            )
        if not old_normalized:
            return microcompacted
        self._logger.info(
            "context_compaction_started",
            session_id=str(context.session.id),
            actor_type=context.session.actor_type,
            tokens_before=tokens_before,
            message_count=len(active_raw),
            forced=force,
        )
        if self._memory is not None and context.session.actor_type == "queen":
            await self._memory.reflect_before_compaction(context, provider)
        try:
            summary = await self._compactor.summarize(
                old_normalized,
                context.model,
                provider,
                policy,
            )
            compacted_through = (
                old_messages[-1].sequence
                if old_messages
                else previous.through_sequence
                if previous is not None
                else 0
            )
            eligible_users = [
                message.sequence
                for message in raw_messages
                if message.sequence <= compacted_through
                if message.role == "user"
                and "worker_run_id" not in message.metadata
                and not message.content.startswith("[WORKER_REPORT]")
            ]
            preserved = (
                eligible_users[-policy.max_verbatim_user_messages :]
                if policy.max_verbatim_user_messages
                else []
            )
            recent_normalized, _ = normalize_message_history(recent_messages)
            system_messages = [message for message in messages if message.role == "system"]
            while True:
                checkpoint = self._compactor.build_checkpoint(
                    summary,
                    compacted_through,
                    preserved,
                    tokens_before,
                    recent_normalized,
                )
                selected = messages_for_checkpoint(raw_messages, checkpoint)
                working, _ = normalize_message_history(selected)
                working.insert(
                    0,
                    LLMMessage(role="user", content="[CONTEXT_COMPACTION]\n" + summary),
                )
                compacted = [*system_messages, *working]
                tokens_after = estimate_context_tokens(compacted, tools)
                if tokens_after < policy.trigger_tokens or not preserved:
                    break
                preserved.pop(0)
            checkpoint = checkpoint.model_copy(update={"tokens_after": tokens_after})
            await self._store.save_compaction_checkpoint(context.session.id, checkpoint)
            self._logger.info(
                "context_compaction_completed",
                session_id=str(context.session.id),
                actor_type=context.session.actor_type,
                tokens_before=tokens_before,
                tokens_after=tokens_after,
                through_sequence=checkpoint.through_sequence,
            )
            return compacted
        except Exception as error:
            self._logger.warning(
                "context_compaction_failed",
                session_id=str(context.session.id),
                actor_type=context.session.actor_type,
                error_type=type(error).__name__,
                error=str(error),
                forced=force,
            )
            if force:
                raise
            return microcompacted

    @staticmethod
    def _recent_start(messages: list[MessageRead]) -> int:
        groups = 0
        index = len(messages)
        while index > 0 and groups < 2:
            index -= 1
            if messages[index].role != "tool":
                groups += 1
        while index > 0 and messages[index].role == "tool":
            index -= 1
        if index > 0 and messages[index].role == "assistant" and messages[index].tool_calls:
            return index
        return index


class ColonyRuntime:
    """Own Queen loops, worker concurrency, tools, recovery, and public commands."""

    def __init__(
        self,
        store: LocalColonyStore,
        provider: LLMProvider | None,
        notifier: ColonyEventNotifier,
        settings: Settings,
        tools: ToolRegistry,
        memory: MemoryCoordinator | None = None,
        mcp_manager: MCPManager | None = None,
    ) -> None:
        self._storage = store
        self._notifier = notifier
        self._settings = settings
        self._tools = tools
        self._memory = memory
        self._mcp_manager = mcp_manager
        self._mcp_tools_registered = False
        self._context_manager = FileContextManager(store, settings.llm_timeout_seconds, memory)
        self._provider_override = provider
        self._sessions = SessionManager[AgentLoop]()
        self._worker_semaphore = asyncio.Semaphore(settings.max_concurrent_workers)
        self._background_tasks: set[asyncio.Task[None]] = set()
        self._pending_queen_resumes: set[UUID] = set()
        self._stopping = False
        self._logger = structlog.get_logger(__name__)

    async def start(self) -> None:
        """Recover queued/running sessions after an application restart."""

        self._stopping = False
        if self._mcp_manager is not None:
            await self._mcp_manager.start()
            if not self._mcp_tools_registered:
                adapters = self._mcp_manager.tool_adapters()
                for tool in adapters:
                    self._tools.register(tool)
                self._mcp_tools_registered = bool(adapters)
        if self._memory is not None:
            await self._memory.initialize()
        worker_ids, queen_ids = await self._storage.recover_interrupted()
        if await self._storage.get_user_llm_runtime_config() is None:
            self._logger.info(
                "llm_settings_required",
                queued_workers=len(worker_ids),
                queued_queens=len(queen_ids),
            )
            return
        for worker_id in worker_ids:
            worker = await self._storage.get_worker(worker_id)
            self._schedule(
                self._run_worker(worker_id),
                worker.owner_session_id if worker is not None else None,
            )
        for session_id in queen_ids:
            self._schedule(self._run_queen(session_id), session_id)

    async def stop(self) -> None:
        self._stopping = True
        tasks = tuple(self._background_tasks)
        if tasks:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        if self._memory is not None:
            await self._memory.stop()
        if self._mcp_manager is not None:
            await self._mcp_manager.close()
        self._sessions.clear()
        self._pending_queen_resumes.clear()

    async def create_colony(self, payload: ColonyCreate) -> ColonyRead:
        queen = await self._storage.get_queen(payload.queen_id)
        if queen is None:
            raise QueenNotFoundError(payload.queen_id)
        await self._require_llm_settings()
        colony, queen_session = await self._storage.create(
            payload.name,
            payload.description,
            payload.queen_id,
            payload.settings,
        )
        await self._storage.append_event(
            colony.id,
            "colony.created",
            session_id=queen_session.id,
            payload={"name": colony.name},
        )
        await self._notifier.notify(queen_session.id)
        return colony

    @property
    def memory_store(self) -> LocalMemoryStore:
        """Return the configured long-term memory store."""

        if self._memory is None:
            raise RuntimeError("Memory coordinator is not configured")
        return self._memory.store

    async def create_queen(self, payload: QueenCreate) -> QueenRead:
        return await self._storage.create_queen(payload)

    async def get_user_settings(self) -> UserSettingsRead:
        return await self._storage.get_user_settings()

    async def update_user_settings(self, payload: UserSettingsUpdate) -> UserSettingsRead:
        was_configured = await self._storage.get_user_llm_runtime_config() is not None
        result = await self._storage.update_user_settings(payload)
        self._sessions.clear()
        if not was_configured:
            worker_ids, queen_ids = await self._storage.recover_interrupted()
            for worker_id in worker_ids:
                worker = await self._storage.get_worker(worker_id)
                self._schedule(
                    self._run_worker(worker_id),
                    worker.owner_session_id if worker is not None else None,
                )
            for session_id in queen_ids:
                self._schedule(self._run_queen(session_id), session_id)
        return result

    async def create_session(self, payload: SessionCreate) -> SessionRead:
        if await self._storage.get_queen(payload.queen_id) is None:
            raise QueenNotFoundError(payload.queen_id)
        if payload.source_session_id is not None:
            raise SessionConflictError(
                "Use the Colony confirmation endpoint to fork an existing Session"
            )
        try:
            session = (
                await self._storage.create_colony_session(payload.queen_id, payload.colony_id)
                if payload.colony_id is not None
                else await self._storage.create_dm_session(payload.queen_id)
            )
        except ValueError as error:
            raise SessionConflictError(str(error)) from error
        await self._storage.append_session_event(
            session.id,
            "session.created",
            payload={"mode": session.mode},
        )
        await self._notifier.notify(session.id)
        return session

    async def list_sessions(self, queen_id: str | None = None) -> list[SessionRead]:
        if queen_id is None:
            return await self._storage.list_sessions()
        if await self._storage.get_queen(queen_id) is None:
            raise QueenNotFoundError(queen_id)
        return await self._storage.list_queen_sessions(queen_id)

    async def list_queens(self) -> list[QueenRead]:
        return await self._storage.list_queens()

    async def get_queen(self, queen_id: str) -> QueenRead:
        queen = await self._storage.get_queen(queen_id)
        if queen is None:
            raise QueenNotFoundError(queen_id)
        return queen

    async def fork_session_into_colony(
        self, session_id: UUID, payload: ColonyForkCreate
    ) -> ColonyRead:
        await self._require_llm_settings()
        try:
            colony, target = await self._storage.fork_dm_session(session_id, payload)
        except KeyError as error:
            raise SessionNotFoundError(str(session_id)) from error
        except ValueError as error:
            raise SessionConflictError(str(error)) from error
        source = await self._storage.get_session(session_id)
        suggestion = source.pending_colony_suggestion if source is not None else None
        if suggestion is not None:
            initial_tasks = [
                await self._storage.create_task_item(
                    colony.id,
                    target.id,
                    TaskItemCreate(title=title, position=position),
                )
                for position, title in enumerate(suggestion.proposed_tasks)
            ]
            task_manifest = "\n".join(f"- {task.id}: {task.title}" for task in initial_tasks)
            handoff_message = await self._storage.append_message(
                target.id,
                LLMMessage(
                    role="user",
                    content=(
                        "[COLONY_FORK]\n"
                        f"目标：{suggestion.goal}\n"
                        f"创建原因：{suggestion.reason}\n"
                        f"工作交接：{suggestion.handoff}\n"
                        "初始任务（调用 run_worker 时将对应 UUID 放入 data.task_id）：\n"
                        f"{task_manifest or '- 无'}"
                    ),
                ),
                metadata={
                    "source_session_id": str(session_id),
                    "system_generated": True,
                    "visibility": "internal",
                },
            )
            if handoff_message is None:
                raise SessionNotFoundError(str(target.id))
        queued = await self._storage.set_session_status(target.id, SessionStatus.QUEUED)
        if not queued:
            raise SessionNotFoundError(str(target.id))
        await self._storage.append_event(
            colony.id,
            "colony.created",
            session_id=target.id,
            payload={"name": colony.name, "source_session_id": str(session_id)},
        )
        await self._notifier.notify(target.id)
        self._schedule(self._run_queen(target.id), target.id)
        return colony

    async def dismiss_colony_suggestion(self, session_id: UUID) -> SessionRead:
        session = await self.get_session(session_id)
        suggestion = session.pending_colony_suggestion
        if suggestion is None or suggestion.status != "pending":
            raise SessionConflictError("当前没有待处理的 Colony 建议")
        updated = await self._storage.set_colony_suggestion(
            session_id, suggestion.model_copy(update={"status": "dismissed"})
        )
        if updated is None:
            raise SessionNotFoundError(str(session_id))
        await self._storage.append_session_event(
            session_id,
            "colony.suggestion.dismissed",
            payload={"suggestion_id": str(suggestion.id)},
        )
        await self._notifier.notify(session_id)
        return updated

    async def list_colonies(self) -> list[ColonyRead]:
        return await self._storage.list_colonies()

    async def delete_colony(self, colony_id: UUID) -> None:
        session_ids = [
            session.id
            for session in await self._storage.list_sessions()
            if session.colony_id == colony_id
        ]
        for session_id in session_ids:
            await self._sessions.cancel_tasks(session_id)
        deleted = await self._storage.delete_colony(colony_id)
        if not deleted:
            raise ColonyNotFoundError(str(colony_id))
        for session_id in session_ids:
            self._sessions.discard(session_id)
            await self._notifier.notify(session_id)

    async def delete_session(self, session_id: UUID) -> None:
        session = await self._storage.get_session(session_id)
        if session is None:
            raise SessionNotFoundError(str(session_id))
        try:
            deleted = await self._storage.delete_session(session_id)
        except ValueError as error:
            raise SessionConflictError(str(error)) from error
        if not deleted:
            raise SessionNotFoundError(str(session_id))
        self._sessions.discard(session_id)
        await self._notifier.notify(session_id)

    async def get_snapshot(self, colony_id: UUID) -> ColonySnapshot:
        colony = await self._storage.get(colony_id)
        queen = await self._storage.get_queen_session(colony_id)
        if colony is None or queen is None:
            raise ColonyNotFoundError(str(colony_id))
        return ColonySnapshot(
            colony=colony,
            session=queen,
            workers=await self._storage.list_workers(colony_id),
            tasks=await self._storage.list_tasks(colony_id),
        )

    async def get_session(self, session_id: UUID) -> SessionRead:
        result = await self._storage.get_session(session_id)
        if result is None:
            raise SessionNotFoundError(str(session_id))
        return result

    async def list_messages(self, session_id: UUID) -> list[MessageRead]:
        result = await self._storage.list_messages(session_id)
        if result is None:
            raise SessionNotFoundError(str(session_id))
        return [
            message
            for message in result
            if message.metadata.get("visibility") != "internal"
            and not (
                message.metadata.get("system_generated") is True
                and message.content.lstrip().startswith("[COLONY_FORK]")
            )
        ]

    async def submit_message(self, session_id: UUID, content: str) -> MessageRead:
        agent_session = await self._storage.get_session(session_id)
        if agent_session is None:
            raise SessionNotFoundError(str(session_id))
        await self._require_llm_settings()
        if agent_session.status in {
            SessionStatus.FORKED,
            SessionStatus.COMPLETED,
            SessionStatus.FAILED,
            SessionStatus.CANCELLED,
        }:
            raise SessionConflictError("Session is terminal")
        colony = (
            await self._storage.get(agent_session.colony_id)
            if agent_session.colony_id is not None
            else None
        )
        if agent_session.mode == "colony" and colony is None:
            raise ColonyNotFoundError(str(agent_session.colony_id))
        message = await self._storage.append_message(
            session_id, LLMMessage(role="user", content=content)
        )
        if message is None:
            raise SessionNotFoundError(str(session_id))
        if colony is not None and colony.name == UNTITLED_COLONY_NAME:
            await self._storage.rename_colony(
                colony.id,
                conversation_name_from_message(content),
            )
        await self._storage.set_session_status(session_id, SessionStatus.QUEUED)
        await self._storage.append_session_event(
            agent_session.id,
            "message.created",
            payload={"message_id": str(message.id), "role": "user"},
        )
        await self._notifier.notify(agent_session.id)
        self._schedule(self._run_queen(session_id), session_id)
        return message

    async def list_workers(self, colony_id: UUID) -> list[WorkerRead]:
        if await self._storage.get(colony_id) is None:
            raise ColonyNotFoundError(str(colony_id))
        return await self._storage.list_workers(colony_id)

    async def list_tracker_tables(self, colony_id: UUID) -> list[TrackerTableRead]:
        if await self._storage.get(colony_id) is None:
            raise ColonyNotFoundError(str(colony_id))
        return await self._storage.list_tracker_tables(colony_id)

    async def list_tracker_rows(
        self,
        colony_id: UUID,
        table: str,
        *,
        limit: int,
        offset: int,
        order_by: str | None,
        order_dir: str,
    ) -> TrackerRowsRead:
        if await self._storage.get(colony_id) is None:
            raise ColonyNotFoundError(str(colony_id))
        try:
            return await self._storage.list_tracker_rows(
                colony_id,
                table,
                limit=limit,
                offset=offset,
                order_by=order_by,
                order_dir=order_dir,
            )
        except KeyError as error:
            raise ValueError(f"Tracker 表不存在：{table}") from error

    async def list_tracker_changes(
        self, colony_id: UUID, since: int
    ) -> TrackerChangesRead:
        if await self._storage.get(colony_id) is None:
            raise ColonyNotFoundError(str(colony_id))
        return await self._storage.list_tracker_changes(colony_id, since)

    async def list_tasks(self, colony_id: UUID) -> list[TaskItemRead]:
        if await self._storage.get(colony_id) is None:
            raise ColonyNotFoundError(str(colony_id))
        return await self._storage.list_tasks(colony_id)

    async def list_events_after(
        self, colony_id: UUID, sequence: int
    ) -> list[ColonyEventRead] | None:
        return await self._storage.list_events_after(colony_id, sequence)

    async def list_session_events_after(
        self, session_id: UUID, sequence: int
    ) -> list[ColonyEventRead] | None:
        return await self._storage.list_session_events_after(session_id, sequence)

    def definitions(self, context: LoopContext | ActorType) -> list[ToolDefinition]:
        actor_type = context.session.actor_type if isinstance(context, LoopContext) else context
        phase = context.session.mode if isinstance(context, LoopContext) else "colony"
        common = [
            ToolDefinition(
                name="tracker_upsert",
                description=(
                    "向 Queen 已登记的业务表写入一行。必须包含全部 key_columns；"
                    "对象和数组会编码为 JSON。只写结构化短字段，不把 Markdown 报告塞进表格。"
                ),
                parameters=TrackerUpsert.model_json_schema(),
            ),
            ToolDefinition(
                name="tracker_query",
                description="用只读 SQL 查询 Colony 业务表；仅允许 SELECT/WITH/EXPLAIN。",
                parameters=TrackerQueryInput.model_json_schema(),
            ),
            ToolDefinition(
                name="task_create",
                description="在持久任务计划中创建一个任务项。",
                parameters=TaskItemCreate.model_json_schema(),
            ),
            ToolDefinition(
                name="task_update",
                description="更新持久任务计划中某个任务项的状态。",
                parameters=TaskUpdateInput.model_json_schema(),
            ),
            ToolDefinition(
                name="load_tool_result",
                description="分页读取当前 Session 中已落盘的大型工具完整结果。",
                parameters=LoadToolResultInput.model_json_schema(),
            ),
        ]
        builtins = self._tools.definitions()
        if actor_type == "queen":
            if phase == "dm":
                return [
                    *builtins,
                    common[-1],
                    ToolDefinition(
                        name="suggest_colony",
                        description=(
                            "当工作适合并行、周期性或长期运行时，向用户提出创建 Colony 的建议。"
                            "该工具不会直接创建 Colony。"
                        ),
                        parameters=SuggestColonyInput.model_json_schema(),
                    ),
                ]
            return [
                ToolDefinition(
                    name="tracker_sql",
                    description=(
                        "创建和维护 Colony 的真实 SQLite 业务表。先将目标建模为一张表，"
                        "每个工作单元一行，并定义可判定完成的字段；禁止访问下划线开头的内部表。"
                    ),
                    parameters=TrackerSQLInput.model_json_schema(),
                ),
                ToolDefinition(
                    name="tracker_register_writable",
                    description=(
                        "登记 Worker 可写的业务表、列和冲突键。"
                        "派发 Worker 前先建表、写入初始行并登记；"
                        "复杂批次先派一个 Worker 验证闭环，再扩展并行。"
                    ),
                    parameters=TrackerRegisterWritableInput.model_json_schema(),
                ),
                *common,
                *builtins,
                ToolDefinition(
                    name="run_worker",
                    description=(
                        "动态创建一个或多个并行 Worker，调用立即返回。"
                        "每个 tasks[].data.task_id 必须填写对应 task_create 返回的任务 UUID；"
                        "Worker 终态会自动同步该任务状态。"
                        "可按批次覆盖外层迭代、收尾迭代和工具调用预算。"
                    ),
                    parameters=RunWorkersInput.model_json_schema(),
                ),
            ]
        return [
            *common,
            *builtins,
            ToolDefinition(
                name="report_to_parent",
                description="向 Queen 汇报最终或部分结果，并结束当前 Worker。",
                parameters=ReportInput.model_json_schema(),
            ),
        ]

    async def execute(self, context: LoopContext, tool_call: ToolCall) -> ToolExecutionResult:
        try:
            if tool_call.argument_error is not None:
                return self._tool_error("TOOL_ARGUMENTS_INVALID", tool_call.argument_error)
            if tool_call.name == "suggest_colony":
                if context.session.actor_type != "queen" or context.session.mode != "dm":
                    return self._tool_error(
                        "TOOL_NOT_ALLOWED", "只有独立阶段的 Queen 可以建议创建 Colony"
                    )
                payload = SuggestColonyInput.model_validate(tool_call.arguments)
                suggestion = await self._suggest_colony(context, payload)
                return ToolExecutionResult(suggestion.model_dump(mode="json"))
            if tool_call.name == "run_worker":
                if context.session.actor_type != "queen" or context.session.mode != "colony":
                    return self._tool_error("TOOL_NOT_ALLOWED", "只有 Colony Queen 可以派生 Worker")
                payload = RunWorkersInput.model_validate(tool_call.arguments)
                workers = await self._spawn_workers(
                    context,
                    payload.tasks,
                    payload.timeout,
                    payload.budget_overrides(),
                )
                return ToolExecutionResult(
                    await self._spill_tool_result(
                        context,
                        tool_call.name,
                        {"workers": [worker.model_dump(mode="json") for worker in workers]},
                    )
                )
            if tool_call.name == "report_to_parent":
                if context.session.actor_type != "worker":
                    return self._tool_error("TOOL_NOT_ALLOWED", "只有 Worker 可以汇报")
                payload = ReportInput.model_validate(tool_call.arguments)
                await self._report_worker(
                    context,
                    WorkerReport.model_validate(payload.model_dump()),
                )
                return ToolExecutionResult({"status": "reported"}, terminate=True)
            if tool_call.name == "tracker_sql":
                if context.session.actor_type != "queen" or context.session.mode != "colony":
                    return self._tool_error(
                        "TOOL_NOT_ALLOWED", "只有 Colony Queen 可以执行 Tracker SQL"
                    )
                payload = TrackerSQLInput.model_validate(tool_call.arguments)
                result = await self._tracker_sql(context, payload)
                return ToolExecutionResult(
                    await self._spill_tool_result(context, tool_call.name, result)
                )
            if tool_call.name == "tracker_register_writable":
                if context.session.actor_type != "queen" or context.session.mode != "colony":
                    return self._tool_error(
                        "TOOL_NOT_ALLOWED", "只有 Colony Queen 可以登记 Tracker 写权限"
                    )
                payload = TrackerRegisterWritableInput.model_validate(tool_call.arguments)
                result = await self._tracker_register_writable(context, payload)
                return ToolExecutionResult(result)
            if tool_call.name == "tracker_upsert":
                if context.session.colony_id is None:
                    return self._tool_error("TOOL_NOT_ALLOWED", "独立会话没有 Tracker")
                payload = TrackerUpsert.model_validate(tool_call.arguments)
                return ToolExecutionResult(await self._tracker_upsert(context, payload))
            if tool_call.name == "tracker_query":
                if context.session.colony_id is None:
                    return self._tool_error("TOOL_NOT_ALLOWED", "独立会话没有 Tracker")
                payload = TrackerQueryInput.model_validate(tool_call.arguments)
                result = await self._storage.query_tracker(
                    context.session.colony_id, payload.sql, payload.row_cap
                )
                return ToolExecutionResult(
                    await self._spill_tool_result(
                        context,
                        tool_call.name,
                        result,
                    )
                )
            if tool_call.name == "task_create":
                if context.session.colony_id is None:
                    return self._tool_error("TOOL_NOT_ALLOWED", "独立会话没有 Colony 任务计划")
                payload = TaskItemCreate.model_validate(tool_call.arguments)
                item = await self._task_create(context, payload)
                return ToolExecutionResult(item.model_dump(mode="json"))
            if tool_call.name == "task_update":
                if context.session.colony_id is None:
                    return self._tool_error("TOOL_NOT_ALLOWED", "独立会话没有 Colony 任务计划")
                payload = TaskUpdateInput.model_validate(tool_call.arguments)
                item = await self._task_update(context, payload)
                return ToolExecutionResult(item.model_dump(mode="json"))
            if tool_call.name == "load_tool_result":
                payload = LoadToolResultInput.model_validate(tool_call.arguments)
                value = await self._storage.read_tool_spillover(
                    context.session.id,
                    payload.filename,
                    payload.offset,
                    min(
                        payload.limit,
                        ContextPolicy.from_mapping(context.session.budget).max_tool_result_chars,
                    ),
                )
                return ToolExecutionResult(value)
            builtin_names = {definition.name for definition in self._tools.definitions()}
            if tool_call.name in builtin_names:
                workspace_root = self._storage.root / "workspaces" / str(context.session.id)
                await asyncio.to_thread(workspace_root.mkdir, parents=True, exist_ok=True)
                worker = (
                    await self._storage.get_worker(context.session.id)
                    if context.session.actor_type == "worker"
                    else None
                )
                value = await self._tools.execute_unbounded(
                    tool_call.name,
                    tool_call.arguments,
                    builtin_names,
                    ToolContext(
                        task_context=context.session.task,
                        upstream_outputs={},
                        session_id=str(context.session.id),
                        colony_id=(
                            str(context.session.colony_id)
                            if context.session.colony_id is not None
                            else None
                        ),
                        queen_id=context.session.queen_id,
                        actor_type=context.session.actor_type,
                        worker_id=str(worker.id) if worker is not None else None,
                        workspace_root=str(workspace_root),
                    ),
                )
                return ToolExecutionResult(
                    await self._spill_tool_result(context, tool_call.name, value)
                )
            return self._tool_error("TOOL_NOT_FOUND", f"未知工具：{tool_call.name}")
        except ToolError as error:
            return ToolExecutionResult(error.as_payload())
        except FileNotFoundError as error:
            return self._tool_error("TOOL_RESULT_NOT_FOUND", str(error))
        except (ValidationError, TrackerPermissionError, ValueError, sqlite3.Error) as error:
            return self._tool_error("TOOL_ARGUMENTS_INVALID", str(error))

    async def _spill_tool_result(
        self, context: LoopContext, tool_name: str, value: JsonValue
    ) -> JsonValue:
        serialized = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        policy = ContextPolicy.from_mapping(context.session.budget)
        if len(serialized) <= policy.max_tool_result_chars:
            return value
        filename = await self._storage.write_tool_spillover(context.session.id, tool_name, value)
        self._logger.info(
            "tool_result_spilled",
            session_id=str(context.session.id),
            actor_type=context.session.actor_type,
            tool_name=tool_name,
            result_chars=len(serialized),
            truncated=True,
        )
        preview_size = max(500, policy.max_tool_result_chars - 500)
        return {
            "truncated": True,
            "preview": serialized[:preview_size],
            "full_result_file": filename,
            "original_chars": len(serialized),
            "hint": "使用 load_tool_result 分页读取完整结果。",
        }

    async def _suggest_colony(
        self, context: LoopContext, payload: SuggestColonyInput
    ) -> ColonySuggestion:
        session = await self._storage.get_session(context.session.owner_session_id)
        if session is None:
            raise SessionNotFoundError(str(context.session.owner_session_id))
        current = session.pending_colony_suggestion
        if current is not None and current.status == "pending":
            raise SessionConflictError("当前已有待用户处理的 Colony 建议")
        suggestion = ColonySuggestion(
            id=uuid4(),
            **payload.model_dump(),
            created_at=utc_now(),
        )
        updated = await self._storage.set_colony_suggestion(context.session.id, suggestion)
        if updated is None:
            raise SessionNotFoundError(str(context.session.id))
        await self._storage.append_session_event(
            context.session.id,
            "colony.suggested",
            payload={
                "suggestion_id": str(suggestion.id),
                "suggested_name": suggestion.suggested_name,
                "reason": suggestion.reason,
            },
        )
        await self._notifier.notify(context.session.id)
        return suggestion

    async def finalize_text(self, context: LoopContext, content: str) -> None:
        if context.session.actor_type == "worker":
            await self._report_worker(
                context,
                WorkerReport(status="success", summary=content, data={}),
            )

    async def finalize_budget_exhausted(
        self,
        context: LoopContext,
        content: str,
        reason: BudgetReason,
    ) -> None:
        if context.session.actor_type == "worker":
            await self._report_worker(
                context,
                WorkerReport(
                    status="partial",
                    summary=content,
                    data={"budget_reason": reason},
                ),
            )

    async def _spawn_workers(
        self,
        context: LoopContext,
        tasks: list[WorkerTask],
        timeout: int,
        budget_overrides: dict[str, int] | None = None,
    ) -> list[WorkerRead]:
        colony_id = self._require_colony_id(context)
        task_items = {item.id: item for item in await self._storage.list_tasks(colony_id)}
        bound_tasks: list[TaskItemRead] = []
        seen_task_ids: set[UUID] = set()
        for worker_task in tasks:
            task_id = self._worker_task_id(worker_task)
            task_item = task_items.get(task_id)
            if task_item is None or task_item.session_id != context.session.owner_session_id:
                raise ValueError(f"Worker 绑定的任务项不存在：{task_id}")
            if task_item.status in {TaskItemStatus.COMPLETED, TaskItemStatus.CANCELLED}:
                raise ValueError(f"Worker 不能绑定已结束的任务项：{task_id}")
            if task_item.assigned_worker_id is not None or task_id in seen_task_ids:
                raise ValueError(f"任务项已经绑定 Worker：{task_id}")
            seen_task_ids.add(task_id)
            bound_tasks.append(task_item)
        workers = await self._storage.create_workers(
            context.session.id,
            tasks,
            timeout,
            budget_overrides,
        )
        for worker, task_item in zip(workers, bound_tasks, strict=True):
            assigned = await self._storage.assign_worker_to_task(task_item.id, worker.id)
            if assigned is None:
                raise RuntimeError(f"无法绑定 Worker {worker.id} 到任务 {task_item.id}")
            await self._storage.append_event(
                colony_id,
                "worker.queued",
                session_id=worker.owner_session_id,
                worker_run_id=worker.id,
                payload={"task": worker.task},
            )
            await self._storage.append_event(
                colony_id,
                "task.updated",
                session_id=worker.owner_session_id,
                worker_run_id=worker.id,
                payload={
                    "task_id": str(assigned.id),
                    "status": assigned.status,
                    "assigned_worker_id": str(worker.id),
                },
            )
        await self._notifier.notify(context.session.owner_session_id)
        for worker in workers:
            self._schedule(self._run_worker(worker.id), worker.owner_session_id)
        return workers

    @staticmethod
    def _worker_task_id(worker_task: WorkerTask) -> UUID:
        value = worker_task.data.get("task_id")
        if not isinstance(value, str):
            raise ValueError("run_worker 的每个 tasks[].data 必须包含 task_id")
        try:
            return UUID(value)
        except ValueError as error:
            raise ValueError("run_worker 的 tasks[].data.task_id 必须是有效 UUID") from error

    async def _run_worker(self, worker_id: UUID) -> None:
        worker = await self._storage.get_worker(worker_id)
        if worker is None or worker.status is not WorkerStatus.QUEUED:
            return
        execution_task: asyncio.Task[None] | None = None
        try:
            worker_loop = self._build_worker_loop(await self._provider_for_session(worker.id))
            execution_task = asyncio.create_task(
                self._execute_worker(worker.id, worker_loop),
                name=f"agentloom-worker-{worker.id}",
            )
            await self._supervise_worker(
                worker,
                worker_loop,
                execution_task,
                soft_timeout_seconds=float(worker.timeout_seconds),
                hard_timeout_seconds=worker_hard_timeout_seconds(worker.timeout_seconds),
            )
        except asyncio.CancelledError:
            if execution_task is not None:
                await self._cancel_worker_execution(execution_task, worker.id)
            raise
        except Exception as error:
            if execution_task is not None:
                await self._cancel_worker_execution(execution_task, worker.id)
            safe_error = sanitize_text(str(error))
            self._logger.error(
                "worker_execution_failed",
                worker_run_id=str(worker.id),
                session_id=str(worker.id),
                error_type=type(error).__name__,
                error=safe_error,
            )
            saved = await self._storage.finish_worker_if_active(
                worker.id,
                WorkerStatus.FAILED,
                error={"code": "WORKER_RUNTIME_FAILED", "message": safe_error},
            )
            if saved is not None:
                await self._storage.append_event(
                    worker.colony_id,
                    "worker.failed",
                    session_id=worker.owner_session_id,
                    worker_run_id=worker.id,
                    payload={"message": safe_error},
                )
                await self._notifier.notify(worker.owner_session_id)
        await self._ensure_worker_terminal_report(worker.id)

    async def _execute_worker(self, worker_id: UUID, worker_loop: AgentLoop) -> None:
        async with self._worker_semaphore:
            worker = await self._storage.mark_worker_running(worker_id)
            if worker is None:
                return
            await self._storage.append_event(
                worker.colony_id,
                "worker.started",
                session_id=worker.owner_session_id,
                worker_run_id=worker.id,
                payload={"task": worker.task},
            )
            await self._notifier.notify(worker.owner_session_id)
            await self._run_serial(worker.id, worker_loop)

    async def _supervise_worker(
        self,
        worker: WorkerRead,
        worker_loop: AgentLoop,
        execution_task: asyncio.Task[None],
        *,
        soft_timeout_seconds: float,
        hard_timeout_seconds: float,
    ) -> None:
        if await self._wait_for_worker(execution_task, soft_timeout_seconds):
            await execution_task
            return

        current = await self._storage.get_worker(worker.id)
        if (
            not execution_task.done()
            and current is not None
            and current.status in ACTIVE_WORKER_STATUSES
            and current.report is None
        ):
            grace_seconds = hard_timeout_seconds - soft_timeout_seconds
            await worker_loop.inject_user_message(
                "[SOFT_TIMEOUT]\n"
                "你已达到软超时。请停止扩展调查，立即基于已有结果收尾，"
                "优先通过 report_to_parent 返回成功、部分结果或失败报告。"
            )
            await self._storage.append_event(
                worker.colony_id,
                "worker.soft_timeout",
                session_id=worker.owner_session_id,
                worker_run_id=worker.id,
                payload={
                    "soft_timeout_seconds": soft_timeout_seconds,
                    "hard_timeout_seconds": hard_timeout_seconds,
                    "grace_seconds": grace_seconds,
                },
            )
            await self._notifier.notify(worker.owner_session_id)
            self._logger.warning(
                "worker_soft_timeout",
                worker_run_id=str(worker.id),
                session_id=str(worker.id),
                soft_timeout_seconds=soft_timeout_seconds,
                hard_timeout_seconds=hard_timeout_seconds,
            )

        remaining_seconds = max(0.0, hard_timeout_seconds - soft_timeout_seconds)
        if await self._wait_for_worker(execution_task, remaining_seconds):
            await execution_task
            return

        await self._cancel_worker_execution(execution_task, worker.id)
        current = await self._storage.get_worker(worker.id)
        if (
            current is None
            or current.status not in ACTIVE_WORKER_STATUSES
            or current.report is not None
        ):
            return
        queued = current.status is WorkerStatus.QUEUED
        error = {
            "code": "WORKER_QUEUE_TIMEOUT" if queued else "WORKER_HARD_TIMEOUT",
            "message": (
                "Worker 在并发队列中等待超过硬超时"
                if queued
                else "Worker 在软超时宽限期后仍未完成，已强制停止"
            ),
        }
        saved = await self._storage.finish_worker_if_active(
            worker.id,
            WorkerStatus.TIMED_OUT,
            error=error,
        )
        if saved is None:
            return
        await self._storage.append_event(
            worker.colony_id,
            "worker.timed_out",
            session_id=worker.owner_session_id,
            worker_run_id=worker.id,
            payload={
                "timeout_seconds": worker.timeout_seconds,
                "soft_timeout_seconds": soft_timeout_seconds,
                "hard_timeout_seconds": hard_timeout_seconds,
            },
        )
        await self._notifier.notify(worker.owner_session_id)
        self._logger.warning(
            "worker_hard_timeout",
            worker_run_id=str(worker.id),
            session_id=str(worker.id),
            queued=queued,
            soft_timeout_seconds=soft_timeout_seconds,
            hard_timeout_seconds=hard_timeout_seconds,
        )

    @staticmethod
    async def _wait_for_worker(
        execution_task: asyncio.Task[None],
        timeout_seconds: float,
    ) -> bool:
        done, _ = await asyncio.wait(
            {execution_task},
            timeout=max(0.0, timeout_seconds),
        )
        return execution_task in done

    async def _cancel_worker_execution(
        self,
        execution_task: asyncio.Task[None],
        worker_id: UUID,
    ) -> None:
        if execution_task.done():
            await asyncio.gather(execution_task, return_exceptions=True)
            return
        execution_task.cancel()
        done, _ = await asyncio.wait(
            {execution_task},
            timeout=WORKER_STOP_TIMEOUT_SECONDS,
        )
        if execution_task not in done:
            self._logger.warning(
                "worker_cancel_cleanup_timed_out",
                worker_run_id=str(worker_id),
                timeout_seconds=WORKER_STOP_TIMEOUT_SECONDS,
            )
            return
        await asyncio.gather(execution_task, return_exceptions=True)

    async def _report_worker(self, context: LoopContext, report: WorkerReport) -> None:
        status_map = {
            "success": WorkerStatus.COMPLETED,
            "partial": WorkerStatus.PARTIAL,
            "failed": WorkerStatus.FAILED,
        }
        report_payload = report.model_dump(mode="json")
        worker = await self._storage.finish_worker_if_active(
            context.session.id,
            status_map[report.status],
            report=report_payload,
            error=(
                {"code": "WORKER_REPORTED_FAILURE", "message": report.summary}
                if report.status == "failed"
                else None
            ),
        )
        if worker is None:
            current = await self._storage.get_worker(context.session.id)
            if current is None:
                raise SessionConflictError("Worker execution has no owning Worker")
            self._logger.info(
                "worker_report_ignored_terminal",
                worker_run_id=str(current.id),
                session_id=str(context.session.id),
                status=current.status,
            )
            return
        await self._publish_worker_report(worker, report_payload)

    async def _ensure_worker_terminal_report(self, worker_id: UUID) -> None:
        worker = await self._storage.get_worker(worker_id)
        terminal_statuses = {
            WorkerStatus.COMPLETED,
            WorkerStatus.PARTIAL,
            WorkerStatus.FAILED,
            WorkerStatus.TIMED_OUT,
            WorkerStatus.CANCELLED,
        }
        if worker is None or worker.status not in terminal_statuses:
            return

        if worker.report is not None:
            queen_messages = await self._storage.list_messages(worker.owner_session_id)
            already_published = queen_messages is not None and any(
                message.metadata.get("worker_run_id") == str(worker.id)
                for message in queen_messages
            )
            if not already_published:
                await self._publish_worker_report(worker, dict(worker.report))
            return

        error_message = worker.error.get("message") if worker.error is not None else None
        safe_error = sanitize_text(error_message) if isinstance(error_message, str) else "未知错误"
        if worker.status is WorkerStatus.TIMED_OUT:
            summary = f"Worker 执行超时：{safe_error}"
        elif worker.status is WorkerStatus.CANCELLED:
            summary = "Worker 在完成前被取消。"
        elif worker.status is WorkerStatus.FAILED:
            summary = f"Worker 执行失败：{safe_error}"
        else:
            summary = "Worker 已结束，但没有生成显式报告。"

        data: dict[str, JsonValue] = {
            "synthetic_report": True,
            "worker_status": worker.status.value,
        }
        error_code = worker.error.get("code") if worker.error is not None else None
        if isinstance(error_code, str):
            data["error_code"] = error_code
        report_payload: dict[str, JsonValue] = {
            "status": (
                "partial"
                if worker.status in {WorkerStatus.COMPLETED, WorkerStatus.PARTIAL}
                else "failed"
            ),
            "summary": summary,
            "data": data,
        }
        messages = await self._storage.list_messages(worker.id)
        if messages is not None:
            last_assistant = next(
                (
                    message.content
                    for message in reversed(messages)
                    if message.role == "assistant" and message.content.strip()
                ),
                None,
            )
            if last_assistant is not None:
                data["last_assistant_excerpt"] = sanitize_text(
                    last_assistant,
                    maximum=2_000,
                )
        saved = await self._storage.attach_worker_report_if_missing(
            worker.id,
            report_payload,
        )
        if saved is None:
            return
        await self._publish_worker_report(saved, report_payload)

    async def _publish_worker_report(
        self,
        worker: WorkerRead,
        report: dict[str, JsonValue],
    ) -> None:
        await self._sync_bound_task(worker)
        queen_message = LLMMessage(
            role="user",
            content="[WORKER_REPORT]\n"
            + json.dumps(report, ensure_ascii=False, separators=(",", ":")),
        )
        await self._storage.append_message(
            worker.owner_session_id,
            queen_message,
            metadata={"worker_run_id": str(worker.id)},
        )
        await self._storage.append_event(
            worker.colony_id,
            "worker.reported",
            session_id=worker.owner_session_id,
            worker_run_id=worker.id,
            payload={
                "status": report.get("status", "failed"),
                "summary": report.get("summary", "Worker 未生成报告。"),
            },
        )
        await self._notifier.notify(worker.owner_session_id)
        workers = [
            item
            for item in await self._storage.list_workers(worker.colony_id)
            if item.owner_session_id == worker.owner_session_id
        ]
        messages = await self._storage.list_messages(worker.owner_session_id)
        reported_worker_ids = {
            worker_id
            for message in messages or []
            if isinstance((worker_id := message.metadata.get("worker_run_id")), str)
        }
        if any(item.status in ACTIVE_WORKER_STATUSES for item in workers) or any(
            str(item.id) not in reported_worker_ids for item in workers
        ):
            return
        await self._storage.set_session_status(worker.owner_session_id, SessionStatus.QUEUED)
        self._schedule_queen_resume(worker.owner_session_id)

    async def _sync_bound_task(self, worker: WorkerRead) -> None:
        tasks = await self._storage.list_tasks(worker.colony_id)
        task = next((item for item in tasks if item.assigned_worker_id == worker.id), None)
        if task is None or task.status in {TaskItemStatus.COMPLETED, TaskItemStatus.CANCELLED}:
            return
        status_map = {
            WorkerStatus.COMPLETED: TaskItemStatus.COMPLETED,
            WorkerStatus.PARTIAL: TaskItemStatus.BLOCKED,
            WorkerStatus.FAILED: TaskItemStatus.BLOCKED,
            WorkerStatus.TIMED_OUT: TaskItemStatus.BLOCKED,
            WorkerStatus.CANCELLED: TaskItemStatus.CANCELLED,
        }
        status = status_map.get(worker.status)
        if status is None:
            return
        updated = await self._storage.update_task_status(task.id, status)
        if updated is None:
            raise RuntimeError(f"Worker {worker.id} 的绑定任务不存在：{task.id}")
        await self._storage.append_event(
            worker.colony_id,
            "task.updated",
            session_id=worker.owner_session_id,
            worker_run_id=worker.id,
            payload={
                "task_id": str(updated.id),
                "status": updated.status,
                "assigned_worker_id": str(worker.id),
                "automatic": True,
            },
        )

    def _schedule_queen_resume(self, session_id: UUID) -> None:
        if self._stopping or session_id in self._pending_queen_resumes:
            return
        self._pending_queen_resumes.add(session_id)

        async def resume() -> None:
            try:
                await self._run_queen(session_id)
            finally:
                self._pending_queen_resumes.discard(session_id)

        self._schedule(resume(), session_id)

    async def _tracker_sql(
        self, context: LoopContext, payload: TrackerSQLInput
    ) -> dict[str, JsonValue]:
        colony_id = self._require_colony_id(context)
        result = await self._storage.execute_tracker_sql(
            colony_id, payload.sql, payload.row_cap
        )
        await self._tracker_changed(context, "tracker.schema_updated", {"operation": "sql"})
        return result

    async def _tracker_register_writable(
        self, context: LoopContext, payload: TrackerRegisterWritableInput
    ) -> dict[str, JsonValue]:
        colony_id = self._require_colony_id(context)
        result = await self._storage.register_tracker_writable(
            colony_id,
            payload.table,
            payload.write_columns,
            payload.key_columns,
        )
        await self._tracker_changed(
            context, "tracker.schema_updated", {"table": payload.table, "operation": "register"}
        )
        return result

    async def _tracker_upsert(
        self, context: LoopContext, payload: TrackerUpsert
    ) -> dict[str, JsonValue]:
        colony_id = self._require_colony_id(context)
        result = await self._storage.upsert_tracker(colony_id, payload)
        await self._tracker_changed(
            context, "tracker.updated", {"table": payload.table, "row": payload.row}
        )
        return result

    async def _tracker_changed(
        self, context: LoopContext, event_type: str, payload: dict[str, JsonValue]
    ) -> None:
        colony_id = self._require_colony_id(context)
        await self._storage.append_event(
            colony_id,
            event_type,
            session_id=context.session.owner_session_id,
            payload=payload,
        )
        await self._notifier.notify(context.session.owner_session_id)

    async def _task_create(self, context: LoopContext, payload: TaskItemCreate) -> TaskItemRead:
        colony_id = self._require_colony_id(context)
        item = await self._storage.create_task_item(colony_id, context.session.id, payload)
        await self._storage.append_event(
            colony_id,
            "task.created",
            session_id=context.session.owner_session_id,
            payload={"task_id": str(item.id), "title": item.title},
        )
        await self._notifier.notify(context.session.owner_session_id)
        return item

    async def _task_update(self, context: LoopContext, payload: TaskUpdateInput) -> TaskItemRead:
        from agentloom.runtime.states import TaskItemStatus

        colony_id = self._require_colony_id(context)
        item = await self._storage.update_task_status(
            payload.task_id, TaskItemStatus(payload.status)
        )
        if item is None or item.colony_id != colony_id:
            raise ValueError("任务项不存在")
        await self._storage.append_event(
            colony_id,
            "task.updated",
            session_id=context.session.owner_session_id,
            payload={"task_id": str(item.id), "status": item.status},
        )
        await self._notifier.notify(context.session.owner_session_id)
        return item

    @staticmethod
    def _require_colony_id(context: LoopContext) -> UUID:
        colony_id = context.session.colony_id
        if colony_id is None:
            raise ValueError("当前会话尚未创建 Colony")
        return colony_id

    def _build_queen_loop(self, provider: LLMProvider | None = None) -> AgentLoop:
        selected_provider = provider or self._provider_override
        if selected_provider is None:
            raise RuntimeError("Queen provider has not been resolved")
        return AgentLoop(
            FileAgentLoopStore(self._storage, self._notifier, self._memory),
            selected_provider,
            self,
            JudgePipeline(),
            default_max_turns=self._settings.queen_max_turns,
            timeout_seconds=self._settings.llm_timeout_seconds,
            observer=self._memory,
            context_manager=self._context_manager,
        )

    def _get_queen_loop(
        self,
        session_id: UUID,
        provider: LLMProvider | None = None,
    ) -> AgentLoop:
        selected_provider = provider or self._provider_override
        if selected_provider is None:
            raise RuntimeError("Queen provider has not been resolved")
        return self._sessions.get_or_create(
            session_id,
            selected_provider,
            self._build_queen_loop,
        ).queen_loop

    def _build_worker_loop(self, provider: LLMProvider | None = None) -> AgentLoop:
        selected_provider = provider or self._provider_override
        if selected_provider is None:
            raise RuntimeError("Worker provider has not been resolved")
        return AgentLoop(
            FileAgentLoopStore(self._storage, self._notifier, self._memory),
            selected_provider,
            self,
            JudgePipeline(),
            default_max_turns=DEFAULT_WORKER_MAX_ITERATIONS,
            timeout_seconds=self._settings.llm_timeout_seconds,
            context_manager=self._context_manager,
        )

    async def _run_queen(self, session_id: UUID) -> None:
        live_session = self._sessions.get(session_id)
        if live_session is None:
            provider = await self._provider_for_session(session_id)
            live_session = self._sessions.get_or_create(
                session_id,
                provider,
                self._build_queen_loop,
            )
        if self._memory is not None:
            seeded = await self._memory.seed_recall(session_id, live_session.provider)
            if not seeded:
                self._memory.schedule_recall(
                    session_id,
                    live_session.provider,
                    lambda content: self._inject_refreshed_memory(session_id, content),
                )
        await self._run_serial(session_id, live_session.queen_loop)

    async def _inject_refreshed_memory(self, session_id: UUID, content: str) -> None:
        execution = await self._storage.get_execution(session_id)
        live_session = self._sessions.get(session_id)
        if (
            execution is None
            or execution.status is not SessionStatus.RUNNING
            or live_session is None
        ):
            return
        await live_session.queen_loop.inject_recalled_memory(content)

    async def _provider_for_session(self, session_id: UUID) -> LLMProvider:
        if self._provider_override is not None:
            return self._provider_override
        execution = await self._storage.get_execution(session_id)
        if execution is None:
            raise SessionNotFoundError(str(session_id))
        if await self._storage.get_queen(execution.queen_id) is None:
            raise QueenNotFoundError(execution.queen_id)
        settings = await self._require_llm_settings()
        return create_llm_provider(settings)

    async def _require_llm_settings(self) -> UserLLMRuntimeConfig:
        settings = await self._storage.get_user_llm_runtime_config()
        if settings is None:
            raise LLMSettingsNotConfiguredError("请先在用户设置中配置 LLM")
        return settings

    async def _run_serial(self, session_id: UUID, loop: AgentLoop) -> None:
        await self._sessions.run(session_id, loop)

    def _schedule(
        self,
        coroutine: Coroutine[object, object, None],
        owner_session_id: UUID | None = None,
    ) -> None:
        if self._stopping:
            coroutine.close()
            return
        task = asyncio.create_task(coroutine)
        self._background_tasks.add(task)
        if owner_session_id is not None:
            self._sessions.track_task(owner_session_id, task)
        task.add_done_callback(self._background_task_done)

    def _background_task_done(self, task: asyncio.Task[None]) -> None:
        self._background_tasks.discard(task)
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            self._logger.error(
                "background_task_failed",
                error_type=type(error).__name__,
                error=sanitize_text(str(error)),
            )

    @staticmethod
    def _tool_error(code: str, message: str) -> ToolExecutionResult:
        return ToolExecutionResult({"error": {"code": code, "message": message}})


def conversation_name_from_message(content: str) -> str:
    normalized = " ".join(content.split())
    return f"{normalized[:32]}…" if len(normalized) > 32 else normalized


__all__ = [
    "ColonyNotFoundError",
    "ColonyRuntime",
    "FileContextManager",
    "FileAgentLoopStore",
    "LLMSettingsNotConfiguredError",
    "QueenNotFoundError",
    "SessionConflictError",
    "SessionNotFoundError",
]
