"""Persistent Queen/Worker Colony runtime and lifecycle commands."""

import asyncio
import json
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
    SessionRead,
    TaskItemCreate,
    TaskItemRead,
    TrackerEntryRead,
    TrackerUpsert,
    WorkerRead,
    WorkerReport,
    WorkerTask,
)
from agentloom.config import Settings
from agentloom.context.compaction import ContextCompactor
from agentloom.context.estimator import estimate_context_tokens
from agentloom.context.schemas import CompactionCheckpoint, ContextPolicy
from agentloom.llm.base import LLMMessage, LLMProvider, ToolCall, ToolDefinition
from agentloom.llm.factory import create_llm_provider
from agentloom.memory.coordinator import MemoryCoordinator
from agentloom.memory.store import LocalMemoryStore
from agentloom.runtime.states import SessionStatus, WorkerStatus
from agentloom.storage import LocalColonyStore, TrackerVersionConflictError
from agentloom.storage.base import utc_now
from agentloom.tools.base import ToolContext, ToolError
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
DEFAULT_WORKER_MAX_TURNS = 8


class ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RunWorkersInput(ToolInput):
    tasks: list[WorkerTask] = Field(min_length=1, max_length=100)
    timeout: int = Field(default=600, ge=1, le=3600)


class ReportInput(ToolInput):
    status: Literal["success", "partial", "failed"]
    summary: str = Field(min_length=1)
    data: dict[str, JsonValue] = Field(default_factory=dict)


class TrackerQueryInput(ToolInput):
    namespace: str | None = None


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
        agent_session = await self._store.get_session(session_id)
        if agent_session is None:
            return None
        colony = (
            await self._store.get(agent_session.colony_id)
            if agent_session.colony_id is not None
            else None
        )
        queen = await self._store.get_queen(agent_session.queen_id)
        llm = await self._store.get_user_llm_runtime_config()
        messages = await self._store.list_messages(session_id)
        if queen is None or messages is None:
            return None
        if agent_session.session_kind == "colony" and colony is None:
            return None
        compaction = await self._store.get_compaction_checkpoint(session_id)
        normalized, repaired_groups = normalize_message_history(
            messages_for_checkpoint(messages, compaction)
        )
        if compaction is not None:
            normalized.insert(
                0,
                LLMMessage(
                    role="user",
                    content="[CONTEXT_COMPACTION]\n" + compaction.summary,
                ),
            )
        if agent_session.actor_type == "queen" and agent_session.colony_id is not None:
            status_context = _worker_status_context(
                await self._store.list_workers(agent_session.colony_id),
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
        effective_session = agent_session
        if llm is not None:
            effective_session = agent_session.model_copy(
                update={
                    "budget": {
                        **agent_session.budget,
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
        current = await self._store.get_session(context.session.id)
        if current is None or current.status in {
            SessionStatus.FORKED,
            SessionStatus.COMPLETED,
            SessionStatus.FAILED,
            SessionStatus.CANCELLED,
        }:
            return False
        await self._store.set_session_status(current.id, SessionStatus.RUNNING)
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
    ) -> None:
        cursor: dict[str, object] = {
            "iteration": iteration,
            "phase": phase,
            "budget_tool_calls": budget_tool_calls,
        }
        if budget_reason is not None:
            cursor["budget_reason"] = budget_reason
            cursor["grace_turn"] = grace_turn
        await self._store.set_session_status(
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
        current = await self._store.get_session(context.session.id)
        if current is None:
            return
        if current.actor_type == "queen":
            await self._store.set_session_status(
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
            await self._store.set_session_status(
                current.id,
                current.status,
                cursor={"iteration": 0, "phase": "completed"},
                usage=usage,
            )
        await self._notifier.notify(self._stream_id(context))

    async def fail(self, context: LoopContext, error: Exception) -> None:
        self._logger.error(
            "agent_session_failed",
            session_id=str(context.session.id),
            actor_type=context.session.actor_type,
            error_type=type(error).__name__,
            error=sanitize_text(str(error)),
        )
        await self._store.set_session_status(context.session.id, SessionStatus.FAILED)
        worker = await self._store.get_worker_for_session(context.session.id)
        if worker is not None:
            await self._store.finish_worker(
                context.session.id,
                WorkerStatus.FAILED,
                error={"code": "AGENT_LOOP_FAILED", "message": str(error)},
            )
        await self._store.append_session_event(
            context.session.id,
            "session.failed",
            worker_run_id=worker.id if worker is not None else None,
            payload={"message": str(error)},
        )
        await self._notifier.notify(self._stream_id(context))

    @staticmethod
    def _stream_id(context: LoopContext) -> UUID:
        return context.session.colony_id or context.session.id


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
    ) -> None:
        self._storage = store
        self._notifier = notifier
        self._settings = settings
        self._tools = tools
        self._memory = memory
        self._context_manager = FileContextManager(store, settings.llm_timeout_seconds, memory)
        self._provider_override = provider
        self._queen_loops: dict[UUID, AgentLoop] = {}
        self._worker_semaphore = asyncio.Semaphore(settings.max_concurrent_workers)
        self._session_locks: dict[UUID, asyncio.Lock] = {}
        self._background_tasks: set[asyncio.Task[None]] = set()
        self._stopping = False
        self._logger = structlog.get_logger(__name__)

    async def start(self) -> None:
        """Recover queued/running sessions after an application restart."""

        self._stopping = False
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
            self._schedule(self._run_worker(worker_id))
        for session_id in queen_ids:
            self._schedule(self._run_queen(session_id))

    async def stop(self) -> None:
        self._stopping = True
        tasks = tuple(self._background_tasks)
        if tasks:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        if self._memory is not None:
            await self._memory.stop()
        self._queen_loops.clear()

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
        await self._notifier.notify(colony.id)
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
        self._queen_loops.clear()
        if not was_configured:
            worker_ids, queen_ids = await self._storage.recover_interrupted()
            for worker_id in worker_ids:
                self._schedule(self._run_worker(worker_id))
            for session_id in queen_ids:
                self._schedule(self._run_queen(session_id))
        return result

    async def create_queen_session(self, queen_id: str) -> SessionRead:
        if await self._storage.get_queen(queen_id) is None:
            raise QueenNotFoundError(queen_id)
        session = await self._storage.create_dm_session(queen_id)
        await self._storage.append_session_event(
            session.id,
            "session.created",
            payload={"session_kind": "dm"},
        )
        await self._notifier.notify(session.id)
        return session

    async def list_queens(self) -> list[QueenRead]:
        return await self._storage.list_queens()

    async def get_queen(self, queen_id: str) -> QueenRead:
        queen = await self._storage.get_queen(queen_id)
        if queen is None:
            raise QueenNotFoundError(queen_id)
        return queen

    async def list_queen_sessions(self, queen_id: str) -> list[SessionRead]:
        if await self._storage.get_queen(queen_id) is None:
            raise QueenNotFoundError(queen_id)
        return await self._storage.list_queen_sessions(queen_id)

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
            await self._storage.append_message(
                target.id,
                LLMMessage(
                    role="user",
                    content=(
                        "[COLONY_FORK]\n"
                        f"目标：{suggestion.goal}\n"
                        f"创建原因：{suggestion.reason}\n"
                        f"工作交接：{suggestion.handoff}"
                    ),
                ),
                metadata={"source_session_id": str(session_id), "system_generated": True},
            )
            for position, title in enumerate(suggestion.proposed_tasks):
                await self._storage.create_task_item(
                    colony.id,
                    target.id,
                    TaskItemCreate(title=title, position=position),
                )
        await self._storage.append_event(
            colony.id,
            "colony.created",
            session_id=target.id,
            payload={"name": colony.name, "source_session_id": str(session_id)},
        )
        await self._notifier.notify(colony.id)
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
        colony = await self._storage.get(colony_id)
        deleted = await self._storage.delete_colony(colony_id)
        if not deleted:
            raise ColonyNotFoundError(str(colony_id))
        if colony is not None and colony.queen_session_id is not None:
            self._queen_loops.pop(colony.queen_session_id, None)
        await self._notifier.notify(colony_id)

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
        self._queen_loops.pop(session_id, None)
        await self._notifier.notify(session_id)

    async def get_snapshot(self, colony_id: UUID) -> ColonySnapshot:
        colony = await self._storage.get(colony_id)
        queen = await self._storage.get_queen_session(colony_id)
        if colony is None or queen is None:
            raise ColonyNotFoundError(str(colony_id))
        return ColonySnapshot(
            colony=colony,
            queen_session=queen,
            workers=await self._storage.list_workers(colony_id),
            tasks=await self._storage.list_tasks(colony_id),
            tracker=await self._storage.list_tracker(colony_id),
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
        return result

    async def submit_message(self, session_id: UUID, content: str) -> MessageRead:
        agent_session = await self._storage.get_session(session_id)
        if agent_session is None:
            raise SessionNotFoundError(str(session_id))
        if agent_session.actor_type != "queen":
            raise SessionConflictError("User messages can only be sent to a queen session")
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
        if agent_session.session_kind == "colony" and colony is None:
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
        await self._notifier.notify(agent_session.colony_id or agent_session.id)
        self._schedule(self._run_queen(session_id))
        return message

    async def list_workers(self, colony_id: UUID) -> list[WorkerRead]:
        if await self._storage.get(colony_id) is None:
            raise ColonyNotFoundError(str(colony_id))
        return await self._storage.list_workers(colony_id)

    async def list_tracker(
        self, colony_id: UUID, namespace: str | None = None
    ) -> list[TrackerEntryRead]:
        if await self._storage.get(colony_id) is None:
            raise ColonyNotFoundError(str(colony_id))
        return await self._storage.list_tracker(colony_id, namespace)

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
        phase = context.session.operating_phase if isinstance(context, LoopContext) else "colony"
        common = [
            ToolDefinition(
                name="tracker_upsert",
                description="在 Colony 共享 Tracker 中新增或更新一条结构化记录。",
                parameters=TrackerUpsert.model_json_schema(),
            ),
            ToolDefinition(
                name="tracker_query",
                description="查询 Colony 共享 Tracker，可按 namespace 过滤。",
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
            if phase == "independent":
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
                *common,
                *builtins,
                ToolDefinition(
                    name="run_worker",
                    description="动态创建一个或多个并行 Worker，调用立即返回。",
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
                if (
                    context.session.actor_type != "queen"
                    or context.session.operating_phase != "independent"
                ):
                    return self._tool_error(
                        "TOOL_NOT_ALLOWED", "只有独立阶段的 Queen 可以建议创建 Colony"
                    )
                payload = SuggestColonyInput.model_validate(tool_call.arguments)
                suggestion = await self._suggest_colony(context, payload)
                return ToolExecutionResult(suggestion.model_dump(mode="json"))
            if tool_call.name == "run_worker":
                if (
                    context.session.actor_type != "queen"
                    or context.session.operating_phase != "colony"
                ):
                    return self._tool_error("TOOL_NOT_ALLOWED", "只有 Colony Queen 可以派生 Worker")
                payload = RunWorkersInput.model_validate(tool_call.arguments)
                workers = await self._spawn_workers(context, payload.tasks, payload.timeout)
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
            if tool_call.name == "tracker_upsert":
                if context.session.colony_id is None:
                    return self._tool_error("TOOL_NOT_ALLOWED", "独立会话没有 Tracker")
                payload = TrackerUpsert.model_validate(tool_call.arguments)
                entry = await self._tracker_upsert(context, payload)
                return ToolExecutionResult(entry.model_dump(mode="json"))
            if tool_call.name == "tracker_query":
                if context.session.colony_id is None:
                    return self._tool_error("TOOL_NOT_ALLOWED", "独立会话没有 Tracker")
                payload = TrackerQueryInput.model_validate(tool_call.arguments)
                entries = await self.list_tracker(context.session.colony_id, payload.namespace)
                return ToolExecutionResult(
                    await self._spill_tool_result(
                        context,
                        tool_call.name,
                        [entry.model_dump(mode="json") for entry in entries],
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
                value = await self._tools.execute_unbounded(
                    tool_call.name,
                    tool_call.arguments,
                    builtin_names,
                    ToolContext(
                        task_context=context.session.task,
                        upstream_outputs={},
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
        except (ValidationError, TrackerVersionConflictError, ValueError) as error:
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
        current = context.session.pending_colony_suggestion
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
        self, context: LoopContext, tasks: list[WorkerTask], timeout: int
    ) -> list[WorkerRead]:
        colony_id = self._require_colony_id(context)
        workers = await self._storage.create_workers(context.session.id, tasks, timeout)
        for worker in workers:
            await self._storage.append_event(
                colony_id,
                "worker.queued",
                session_id=worker.worker_session_id,
                worker_run_id=worker.id,
                payload={"task": worker.task},
            )
        await self._notifier.notify(colony_id)
        for worker in workers:
            self._schedule(self._run_worker(worker.id))
        return workers

    async def _run_worker(self, worker_id: UUID) -> None:
        async with self._worker_semaphore:
            worker = await self._storage.mark_worker_running(worker_id)
            if worker is None:
                return
            await self._storage.append_event(
                worker.colony_id,
                "worker.started",
                session_id=worker.worker_session_id,
                worker_run_id=worker.id,
                payload={"task": worker.task},
            )
            await self._notifier.notify(worker.colony_id)
            worker_loop = self._build_worker_loop(
                await self._provider_for_session(worker.worker_session_id)
            )
            try:
                await asyncio.wait_for(
                    self._run_serial(worker.worker_session_id, worker_loop),
                    timeout=worker.timeout_seconds,
                )
            except TimeoutError:
                await self._storage.finish_worker(
                    worker.worker_session_id,
                    WorkerStatus.TIMED_OUT,
                    error={"code": "WORKER_TIMEOUT", "message": "Worker 执行超时"},
                )
                await self._storage.append_event(
                    worker.colony_id,
                    "worker.timed_out",
                    session_id=worker.worker_session_id,
                    worker_run_id=worker.id,
                    payload={"timeout_seconds": worker.timeout_seconds},
                )
                await self._notifier.notify(worker.colony_id)
            await self._ensure_worker_terminal_report(worker.worker_session_id)

    async def _report_worker(self, context: LoopContext, report: WorkerReport) -> None:
        status_map = {
            "success": WorkerStatus.COMPLETED,
            "partial": WorkerStatus.PARTIAL,
            "failed": WorkerStatus.FAILED,
        }
        report_payload = report.model_dump(mode="json")
        worker = await self._storage.finish_worker(
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
            raise SessionConflictError("Worker session has no owning worker run")
        await self._publish_worker_report(worker, report_payload)

    async def _ensure_worker_terminal_report(self, worker_session_id: UUID) -> None:
        worker = await self._storage.get_worker_for_session(worker_session_id)
        terminal_statuses = {
            WorkerStatus.COMPLETED,
            WorkerStatus.PARTIAL,
            WorkerStatus.FAILED,
            WorkerStatus.TIMED_OUT,
            WorkerStatus.CANCELLED,
        }
        if worker is None or worker.report is not None or worker.status not in terminal_statuses:
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
        saved = await self._storage.finish_worker(
            worker.worker_session_id,
            worker.status,
            report=report_payload,
            error=worker.error,
        )
        if saved is None:
            raise SessionConflictError("Worker session has no owning worker run")
        await self._publish_worker_report(saved, report_payload)

    async def _publish_worker_report(
        self,
        worker: WorkerRead,
        report: dict[str, JsonValue],
    ) -> None:
        queen_message = LLMMessage(
            role="user",
            content="[WORKER_REPORT]\n"
            + json.dumps(report, ensure_ascii=False, separators=(",", ":")),
        )
        await self._storage.append_message(
            worker.queen_session_id,
            queen_message,
            metadata={"worker_run_id": str(worker.id)},
        )
        await self._storage.set_session_status(worker.queen_session_id, SessionStatus.QUEUED)
        await self._storage.append_event(
            worker.colony_id,
            "worker.reported",
            session_id=worker.worker_session_id,
            worker_run_id=worker.id,
            payload={
                "status": report.get("status", "failed"),
                "summary": report.get("summary", "Worker 未生成报告。"),
            },
        )
        await self._notifier.notify(worker.colony_id)
        self._schedule(self._run_queen(worker.queen_session_id))

    async def _tracker_upsert(
        self, context: LoopContext, payload: TrackerUpsert
    ) -> TrackerEntryRead:
        colony_id = self._require_colony_id(context)
        entry = await self._storage.upsert_tracker(colony_id, context.session.id, payload)
        await self._storage.append_event(
            colony_id,
            "tracker.updated",
            session_id=context.session.id,
            payload={
                "namespace": entry.namespace,
                "entry_key": entry.entry_key,
                "version": entry.version,
            },
        )
        await self._notifier.notify(colony_id)
        return entry

    async def _task_create(self, context: LoopContext, payload: TaskItemCreate) -> TaskItemRead:
        colony_id = self._require_colony_id(context)
        item = await self._storage.create_task_item(colony_id, context.session.id, payload)
        await self._storage.append_event(
            colony_id,
            "task.created",
            session_id=context.session.id,
            payload={"task_id": str(item.id), "title": item.title},
        )
        await self._notifier.notify(colony_id)
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
            session_id=context.session.id,
            payload={"task_id": str(item.id), "status": item.status},
        )
        await self._notifier.notify(colony_id)
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
        loop = self._queen_loops.get(session_id)
        if loop is None:
            loop = self._build_queen_loop(provider)
            self._queen_loops[session_id] = loop
        return loop

    def _build_worker_loop(self, provider: LLMProvider | None = None) -> AgentLoop:
        selected_provider = provider or self._provider_override
        if selected_provider is None:
            raise RuntimeError("Worker provider has not been resolved")
        return AgentLoop(
            FileAgentLoopStore(self._storage, self._notifier, self._memory),
            selected_provider,
            self,
            JudgePipeline(),
            default_max_turns=DEFAULT_WORKER_MAX_TURNS,
            timeout_seconds=self._settings.llm_timeout_seconds,
            context_manager=self._context_manager,
        )

    async def _run_queen(self, session_id: UUID) -> None:
        provider = await self._provider_for_session(session_id)
        if self._memory is not None:
            await self._memory.prepare_recall(session_id, provider)
        await self._run_serial(session_id, self._get_queen_loop(session_id, provider))

    async def _provider_for_session(self, session_id: UUID) -> LLMProvider:
        if self._provider_override is not None:
            return self._provider_override
        session = await self._storage.get_session(session_id)
        if session is None:
            raise SessionNotFoundError(str(session_id))
        if await self._storage.get_queen(session.queen_id) is None:
            raise QueenNotFoundError(session.queen_id)
        settings = await self._require_llm_settings()
        return create_llm_provider(settings)

    async def _require_llm_settings(self) -> UserLLMRuntimeConfig:
        settings = await self._storage.get_user_llm_runtime_config()
        if settings is None:
            raise LLMSettingsNotConfiguredError("请先在用户设置中配置 LLM")
        return settings

    async def _run_serial(self, session_id: UUID, loop: AgentLoop) -> None:
        lock = self._session_locks.setdefault(session_id, asyncio.Lock())
        async with lock:
            await loop.run(session_id)

    def _schedule(self, coroutine: Coroutine[object, object, None]) -> None:
        if self._stopping:
            coroutine.close()
            return
        task = asyncio.create_task(coroutine)
        self._background_tasks.add(task)
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
