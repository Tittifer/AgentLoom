"""Persistent Queen/Worker Colony runtime and lifecycle commands."""

import asyncio
import json
from collections.abc import Coroutine
from typing import Literal
from uuid import UUID

import structlog
from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError

from agentloom.agents.judge import JudgePipeline
from agentloom.agents.loop import (
    AgentLoop,
    AgentLoopStore,
    LoopContext,
    ToolExecutionResult,
)
from agentloom.colony.message_safety import sanitize_text
from agentloom.colony.notifier import ColonyEventNotifier
from agentloom.colony.schemas import (
    ActorType,
    ColonyCreate,
    ColonyEventRead,
    ColonyRead,
    ColonySnapshot,
    MessageRead,
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
from agentloom.llm.base import LLMMessage, LLMProvider, ToolCall, ToolDefinition
from agentloom.runtime.states import SessionStatus, WorkerStatus
from agentloom.storage import LocalColonyStore, TrackerVersionConflictError
from agentloom.tools.base import ToolContext, ToolError
from agentloom.tools.registry import ToolRegistry


class ColonyNotFoundError(LookupError):
    """Raised when a Colony command targets an unknown identifier."""


class SessionNotFoundError(LookupError):
    """Raised when a command targets an unknown agent session."""


class SessionConflictError(ValueError):
    """Raised when a session cannot accept the requested transition."""


UNTITLED_COLONY_NAME = "新会话"


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
    ) -> None:
        self._store = store
        self._notifier = notifier
        self._logger = structlog.get_logger(__name__)

    async def load(self, session_id: UUID) -> LoopContext | None:
        agent_session = await self._store.get_session(session_id)
        if agent_session is None:
            return None
        colony = await self._store.get(agent_session.colony_id)
        messages = await self._store.list_messages(session_id)
        if colony is None or messages is None:
            return None
        normalized, repaired_groups = normalize_message_history(messages)
        if agent_session.actor_type == "queen":
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
        return LoopContext(session=agent_session, colony=colony, messages=normalized)

    async def mark_running(self, context: LoopContext) -> bool:
        current = await self._store.get_session(context.session.id)
        if current is None or current.status in {
            SessionStatus.COMPLETED,
            SessionStatus.FAILED,
            SessionStatus.CANCELLED,
        }:
            return False
        await self._store.set_session_status(current.id, SessionStatus.RUNNING)
        await self._store.append_event(
            current.colony_id,
            "session.started",
            session_id=current.id,
            payload={"actor_type": current.actor_type},
        )
        await self._notifier.notify(context.session.colony_id)
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
        await self._store.append_event(
            context.session.colony_id,
            event_type,
            session_id=context.session.id,
            payload={"message_id": str(saved.id), "role": saved.role},
        )
        await self._notifier.notify(context.session.colony_id)
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
            context.session.colony_id,
            "message.delta",
            {
                "colony_id": str(context.session.colony_id),
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
            context.session.colony_id,
            "message.stream.cancelled",
            {
                "colony_id": str(context.session.colony_id),
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
    ) -> None:
        await self._store.set_session_status(
            context.session.id,
            SessionStatus.RUNNING,
            cursor={"iteration": iteration, "phase": phase},
            usage=usage,
        )

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
            await self._store.append_event(
                current.colony_id,
                "session.idle",
                session_id=current.id,
                payload={"actor_type": "queen"},
            )
        else:
            await self._store.set_session_status(
                current.id,
                current.status,
                cursor={"iteration": 0, "phase": "completed"},
                usage=usage,
            )
        await self._notifier.notify(context.session.colony_id)

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
        await self._store.append_event(
            context.session.colony_id,
            "session.failed",
            session_id=context.session.id,
            worker_run_id=worker.id if worker is not None else None,
            payload={"message": str(error)},
        )
        await self._notifier.notify(context.session.colony_id)


class ColonyRuntime:
    """Own Queen loops, worker concurrency, tools, recovery, and public commands."""

    def __init__(
        self,
        store: LocalColonyStore,
        provider: LLMProvider,
        notifier: ColonyEventNotifier,
        settings: Settings,
        tools: ToolRegistry,
    ) -> None:
        self._storage = store
        self._notifier = notifier
        self._settings = settings
        self._tools = tools
        self._store = FileAgentLoopStore(store, notifier)
        self._loop = AgentLoop(
            self._store,
            provider,
            self,
            JudgePipeline(),
            default_max_turns=settings.queen_max_turns,
            timeout_seconds=settings.llm_timeout_seconds,
        )
        self._worker_semaphore = asyncio.Semaphore(settings.max_concurrent_workers)
        self._session_locks: dict[UUID, asyncio.Lock] = {}
        self._background_tasks: set[asyncio.Task[None]] = set()
        self._stopping = False
        self._logger = structlog.get_logger(__name__)

    async def start(self) -> None:
        """Recover queued/running sessions after an application restart."""

        self._stopping = False
        worker_ids, queen_ids = await self._storage.recover_interrupted()
        for worker_id in worker_ids:
            self._schedule(self._run_worker(worker_id))
        for session_id in queen_ids:
            self._schedule(self._run_serial(session_id))

    async def stop(self) -> None:
        self._stopping = True
        tasks = tuple(self._background_tasks)
        if tasks:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def create_colony(self, payload: ColonyCreate) -> ColonyRead:
        colony, queen = await self._storage.create(
            payload.name,
            payload.description,
            payload.queen_profile,
            payload.model or self._settings.llm_model,
            payload.settings,
        )
        await self._storage.append_event(
            colony.id,
            "colony.created",
            session_id=queen.id,
            payload={"name": colony.name},
        )
        await self._notifier.notify(colony.id)
        return colony

    async def list_colonies(self) -> list[ColonyRead]:
        return await self._storage.list_colonies()

    async def delete_colony(self, colony_id: UUID) -> None:
        deleted = await self._storage.delete_colony(colony_id)
        if not deleted:
            raise ColonyNotFoundError(str(colony_id))
        await self._notifier.notify(colony_id)

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
        if agent_session.status in {
            SessionStatus.COMPLETED,
            SessionStatus.FAILED,
            SessionStatus.CANCELLED,
        }:
            raise SessionConflictError("Session is terminal")
        colony = await self._storage.get(agent_session.colony_id)
        if colony is None:
            raise ColonyNotFoundError(str(agent_session.colony_id))
        message = await self._storage.append_message(
            session_id, LLMMessage(role="user", content=content)
        )
        if message is None:
            raise SessionNotFoundError(str(session_id))
        if colony.name == UNTITLED_COLONY_NAME:
            await self._storage.rename_colony(
                agent_session.colony_id,
                conversation_name_from_message(content),
            )
        await self._storage.set_session_status(session_id, SessionStatus.QUEUED)
        await self._storage.append_event(
            agent_session.colony_id,
            "message.created",
            session_id=session_id,
            payload={"message_id": str(message.id), "role": "user"},
        )
        await self._notifier.notify(agent_session.colony_id)
        self._schedule(self._run_serial(session_id))
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

    def definitions(self, actor_type: ActorType) -> list[ToolDefinition]:
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
        ]
        builtins = self._tools.definitions()
        if actor_type == "queen":
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
            if tool_call.name == "run_worker":
                if context.session.actor_type != "queen":
                    return self._tool_error("TOOL_NOT_ALLOWED", "Worker 不能派生其他 Worker")
                payload = RunWorkersInput.model_validate(tool_call.arguments)
                workers = await self._spawn_workers(context, payload.tasks, payload.timeout)
                return ToolExecutionResult(
                    {"workers": [worker.model_dump(mode="json") for worker in workers]}
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
                payload = TrackerUpsert.model_validate(tool_call.arguments)
                entry = await self._tracker_upsert(context, payload)
                return ToolExecutionResult(entry.model_dump(mode="json"))
            if tool_call.name == "tracker_query":
                payload = TrackerQueryInput.model_validate(tool_call.arguments)
                entries = await self.list_tracker(context.session.colony_id, payload.namespace)
                return ToolExecutionResult([entry.model_dump(mode="json") for entry in entries])
            if tool_call.name == "task_create":
                payload = TaskItemCreate.model_validate(tool_call.arguments)
                item = await self._task_create(context, payload)
                return ToolExecutionResult(item.model_dump(mode="json"))
            if tool_call.name == "task_update":
                payload = TaskUpdateInput.model_validate(tool_call.arguments)
                item = await self._task_update(context, payload)
                return ToolExecutionResult(item.model_dump(mode="json"))
            builtin_names = {definition.name for definition in self._tools.definitions()}
            if tool_call.name in builtin_names:
                value = await self._tools.execute(
                    tool_call.name,
                    tool_call.arguments,
                    builtin_names,
                    ToolContext(
                        task_context=context.session.task,
                        upstream_outputs={},
                    ),
                )
                return ToolExecutionResult(value)
            return self._tool_error("TOOL_NOT_FOUND", f"未知工具：{tool_call.name}")
        except ToolError as error:
            return ToolExecutionResult(error.as_payload())
        except (ValidationError, TrackerVersionConflictError, ValueError) as error:
            return self._tool_error("TOOL_ARGUMENTS_INVALID", str(error))

    async def finalize_text(self, context: LoopContext, content: str) -> None:
        if context.session.actor_type == "worker":
            await self._report_worker(
                context,
                WorkerReport(status="success", summary=content, data={}),
            )

    async def _spawn_workers(
        self, context: LoopContext, tasks: list[WorkerTask], timeout: int
    ) -> list[WorkerRead]:
        workers = await self._storage.create_workers(context.session.id, tasks, timeout)
        for worker in workers:
            await self._storage.append_event(
                context.session.colony_id,
                "worker.queued",
                session_id=worker.worker_session_id,
                worker_run_id=worker.id,
                payload={"task": worker.task},
            )
        await self._notifier.notify(context.session.colony_id)
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
            try:
                await asyncio.wait_for(
                    self._run_serial(worker.worker_session_id),
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

    async def _report_worker(self, context: LoopContext, report: WorkerReport) -> None:
        status_map = {
            "success": WorkerStatus.COMPLETED,
            "partial": WorkerStatus.PARTIAL,
            "failed": WorkerStatus.FAILED,
        }
        worker = await self._storage.finish_worker(
            context.session.id,
            status_map[report.status],
            report=report.model_dump(mode="json"),
            error=(
                {"code": "WORKER_REPORTED_FAILURE", "message": report.summary}
                if report.status == "failed"
                else None
            ),
        )
        if worker is None:
            raise SessionConflictError("Worker session has no owning worker run")
        queen_message = LLMMessage(
            role="user",
            content="[WORKER_REPORT]\n" + report.model_dump_json(),
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
            payload={"status": report.status, "summary": report.summary},
        )
        await self._notifier.notify(context.session.colony_id)
        self._schedule(self._run_serial(worker.queen_session_id))

    async def _tracker_upsert(
        self, context: LoopContext, payload: TrackerUpsert
    ) -> TrackerEntryRead:
        entry = await self._storage.upsert_tracker(
            context.session.colony_id, context.session.id, payload
        )
        await self._storage.append_event(
            context.session.colony_id,
            "tracker.updated",
            session_id=context.session.id,
            payload={
                "namespace": entry.namespace,
                "entry_key": entry.entry_key,
                "version": entry.version,
            },
        )
        await self._notifier.notify(context.session.colony_id)
        return entry

    async def _task_create(self, context: LoopContext, payload: TaskItemCreate) -> TaskItemRead:
        item = await self._storage.create_task_item(
            context.session.colony_id, context.session.id, payload
        )
        await self._storage.append_event(
            context.session.colony_id,
            "task.created",
            session_id=context.session.id,
            payload={"task_id": str(item.id), "title": item.title},
        )
        await self._notifier.notify(context.session.colony_id)
        return item

    async def _task_update(self, context: LoopContext, payload: TaskUpdateInput) -> TaskItemRead:
        from agentloom.runtime.states import TaskItemStatus

        item = await self._storage.update_task_status(
            payload.task_id, TaskItemStatus(payload.status)
        )
        if item is None or item.colony_id != context.session.colony_id:
            raise ValueError("任务项不存在")
        await self._storage.append_event(
            context.session.colony_id,
            "task.updated",
            session_id=context.session.id,
            payload={"task_id": str(item.id), "status": item.status},
        )
        await self._notifier.notify(context.session.colony_id)
        return item

    async def _run_serial(self, session_id: UUID) -> None:
        lock = self._session_locks.setdefault(session_id, asyncio.Lock())
        async with lock:
            await self._loop.run(session_id)

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
    "FileAgentLoopStore",
    "SessionConflictError",
    "SessionNotFoundError",
]
