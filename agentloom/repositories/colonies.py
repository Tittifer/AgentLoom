"""Persistence operations for Colony aggregates."""

from collections.abc import Mapping, Sequence
from typing import cast
from uuid import UUID

from pydantic import JsonValue, TypeAdapter
from sqlalchemy import delete, func, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from agentloom.colony.message_safety import sanitize_json, sanitize_text
from agentloom.colony.schemas import (
    ActorType,
    ColonyEventRead,
    ColonyRead,
    MessageRead,
    SessionRead,
    TaskItemCreate,
    TaskItemRead,
    TrackerEntryRead,
    TrackerUpsert,
    WorkerRead,
    WorkerTask,
)
from agentloom.db.base import utc_now
from agentloom.db.models.colony import ColonyModel, default_colony_settings
from agentloom.db.models.colony_event import ColonyEventModel
from agentloom.db.models.conversation import ConversationMessageModel
from agentloom.db.models.session import AgentSessionModel
from agentloom.db.models.task_item import TaskItemModel
from agentloom.db.models.tracker import TrackerEntryModel
from agentloom.db.models.worker import WorkerRunModel
from agentloom.llm.base import LLMMessage
from agentloom.runtime.states import ColonyStatus, SessionStatus, TaskItemStatus, WorkerStatus

JSON_OBJECT = TypeAdapter(dict[str, JsonValue])
JSON_OBJECTS = TypeAdapter(list[dict[str, JsonValue]])


class TrackerVersionConflictError(ValueError):
    """Raised when an optimistic tracker update targets a stale version."""


def colony_lock_key(colony_id: UUID) -> int:
    """Return a deterministic signed PostgreSQL advisory-lock key."""

    upper = colony_id.int >> 64
    lower = colony_id.int & ((1 << 64) - 1)
    value = upper ^ lower
    return value - (1 << 64) if value >= 1 << 63 else value


class ColonyRepository:
    """Read and mutate Colony state inside caller-owned transactions."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def lock_colony_for_write(self, colony_id: UUID) -> None:
        """Serialize writes for one Colony until the current transaction ends."""

        await self._session.execute(select(func.pg_advisory_xact_lock(colony_lock_key(colony_id))))

    async def create(
        self,
        name: str,
        description: str,
        queen_profile: str,
        model: str,
        settings: Mapping[str, object],
    ) -> tuple[ColonyRead, SessionRead]:
        merged_settings = default_colony_settings()
        merged_settings.update(settings)
        colony = ColonyModel(
            name=name,
            description=description,
            status=ColonyStatus.ACTIVE,
            queen_profile=queen_profile,
            model=model,
            settings=merged_settings,
        )
        self._session.add(colony)
        await self._session.flush()
        queen = AgentSessionModel(
            colony_id=colony.id,
            actor_type="queen",
            status=SessionStatus.IDLE,
            task={},
            cursor={"iteration": 0, "phase": "idle"},
            budget=merged_settings,
            usage={"input_tokens": 0, "output_tokens": 0, "tool_calls": 0},
        )
        self._session.add(queen)
        await self._session.flush()
        return self._colony_read(colony, queen.id), self._session_read(queen)

    async def list_colonies(self) -> list[ColonyRead]:
        colonies = (
            await self._session.scalars(select(ColonyModel).order_by(ColonyModel.created_at.desc()))
        ).all()
        result: list[ColonyRead] = []
        for colony in colonies:
            queen_id = await self._session.scalar(
                select(AgentSessionModel.id).where(
                    AgentSessionModel.colony_id == colony.id,
                    AgentSessionModel.actor_type == "queen",
                )
            )
            result.append(self._colony_read(colony, queen_id))
        return result

    async def delete_colony(self, colony_id: UUID) -> bool:
        """Delete one Colony and its database-owned conversation state."""

        await self.lock_colony_for_write(colony_id)
        result = await self._session.execute(
            delete(ColonyModel).where(ColonyModel.id == colony_id)
        )
        return cast(CursorResult[object], result).rowcount > 0

    async def get(self, colony_id: UUID) -> ColonyRead | None:
        colony = await self._session.get(ColonyModel, colony_id)
        if colony is None:
            return None
        queen_id = await self._session.scalar(
            select(AgentSessionModel.id).where(
                AgentSessionModel.colony_id == colony_id,
                AgentSessionModel.actor_type == "queen",
            )
        )
        return self._colony_read(colony, queen_id)

    async def get_session(self, session_id: UUID, *, lock: bool = False) -> SessionRead | None:
        statement = select(AgentSessionModel).where(AgentSessionModel.id == session_id)
        if lock:
            statement = statement.with_for_update()
        model = await self._session.scalar(statement)
        return self._session_read(model) if model is not None else None

    async def get_queen_session(self, colony_id: UUID) -> SessionRead | None:
        model = await self._session.scalar(
            select(AgentSessionModel).where(
                AgentSessionModel.colony_id == colony_id,
                AgentSessionModel.actor_type == "queen",
            )
        )
        return self._session_read(model) if model is not None else None

    async def set_session_status(
        self,
        session_id: UUID,
        status: SessionStatus,
        *,
        park_reason: str | None = None,
        cursor: Mapping[str, object] | None = None,
        usage: Mapping[str, object] | None = None,
    ) -> bool:
        colony_id = await self._session.scalar(
            select(AgentSessionModel.colony_id).where(AgentSessionModel.id == session_id)
        )
        if colony_id is None:
            return False
        await self.lock_colony_for_write(colony_id)

        values: dict[str, object] = {
            "status": status,
            "park_reason": park_reason,
            "updated_at": utc_now(),
        }
        if cursor is not None:
            values["cursor"] = dict(cursor)
        if usage is not None:
            values["usage"] = dict(usage)
        if status in {SessionStatus.COMPLETED, SessionStatus.FAILED, SessionStatus.CANCELLED}:
            values["ended_at"] = utc_now()
        result = await self._session.execute(
            update(AgentSessionModel).where(AgentSessionModel.id == session_id).values(**values)
        )
        return cast(CursorResult[object], result).rowcount > 0

    async def append_message(
        self,
        session_id: UUID,
        message: LLMMessage,
        *,
        metadata: Mapping[str, object] | None = None,
    ) -> MessageRead | None:
        colony_id = await self._session.scalar(
            select(AgentSessionModel.colony_id).where(AgentSessionModel.id == session_id)
        )
        if colony_id is None:
            return None
        await self.lock_colony_for_write(colony_id)

        session = await self._session.scalar(
            select(AgentSessionModel).where(AgentSessionModel.id == session_id).with_for_update()
        )
        if session is None:
            return None
        sequence = await self._session.scalar(
            select(func.coalesce(func.max(ConversationMessageModel.sequence), 0) + 1).where(
                ConversationMessageModel.session_id == session_id
            )
        )
        if sequence is None:
            raise RuntimeError(f"Could not allocate message sequence for {session_id}")
        sanitized_calls = JSON_OBJECTS.validate_python(
            [sanitize_json(call.model_dump(mode="json")) for call in message.tool_calls]
        )
        sanitized_metadata = JSON_OBJECT.validate_python(
            sanitize_json(JSON_OBJECT.validate_python(dict(metadata or {})))
        )
        model = ConversationMessageModel(
            session_id=session_id,
            sequence=sequence,
            role=message.role,
            content=sanitize_text(message.content),
            tool_call_id=message.tool_call_id,
            tool_calls=sanitized_calls,
            metadata_=sanitized_metadata,
        )
        self._session.add(model)
        await self._session.flush()
        return self._message_read(model)

    async def list_messages(self, session_id: UUID) -> list[MessageRead] | None:
        if await self._session.get(AgentSessionModel, session_id) is None:
            return None
        models = (
            await self._session.scalars(
                select(ConversationMessageModel)
                .where(ConversationMessageModel.session_id == session_id)
                .order_by(ConversationMessageModel.sequence)
            )
        ).all()
        return [self._message_read(model) for model in models]

    async def create_workers(
        self,
        queen_session_id: UUID,
        tasks: Sequence[WorkerTask],
        timeout_seconds: int,
    ) -> list[WorkerRead]:
        colony_id = await self._session.scalar(
            select(AgentSessionModel.colony_id).where(
                AgentSessionModel.id == queen_session_id,
                AgentSessionModel.actor_type == "queen",
            )
        )
        if colony_id is None:
            return []
        await self.lock_colony_for_write(colony_id)

        queen = await self._session.scalar(
            select(AgentSessionModel)
            .where(
                AgentSessionModel.id == queen_session_id,
                AgentSessionModel.actor_type == "queen",
            )
            .with_for_update()
        )
        if queen is None:
            return []
        workers: list[WorkerRead] = []
        for task in tasks:
            worker_session = AgentSessionModel(
                colony_id=queen.colony_id,
                parent_session_id=queen.id,
                actor_type="worker",
                status=SessionStatus.QUEUED,
                task={"description": task.task, "data": task.data},
                cursor={"iteration": 0, "phase": "queued"},
                budget={"max_turns": 8, "max_tool_calls": 12},
                usage={"input_tokens": 0, "output_tokens": 0, "tool_calls": 0},
            )
            self._session.add(worker_session)
            await self._session.flush()
            worker = WorkerRunModel(
                colony_id=queen.colony_id,
                queen_session_id=queen.id,
                worker_session_id=worker_session.id,
                status=WorkerStatus.QUEUED,
                task=task.task,
                input=task.data,
                timeout_seconds=timeout_seconds,
            )
            self._session.add(worker)
            await self._session.flush()
            workers.append(self._worker_read(worker))
        return workers

    async def list_workers(self, colony_id: UUID) -> list[WorkerRead]:
        models = (
            await self._session.scalars(
                select(WorkerRunModel)
                .where(WorkerRunModel.colony_id == colony_id)
                .order_by(WorkerRunModel.queued_at.desc())
            )
        ).all()
        return [self._worker_read(model) for model in models]

    async def get_worker_for_session(self, session_id: UUID) -> WorkerRead | None:
        model = await self._session.scalar(
            select(WorkerRunModel).where(WorkerRunModel.worker_session_id == session_id)
        )
        return self._worker_read(model) if model is not None else None

    async def mark_worker_running(self, worker_id: UUID) -> WorkerRead | None:
        colony_id = await self._session.scalar(
            select(WorkerRunModel.colony_id).where(WorkerRunModel.id == worker_id)
        )
        if colony_id is None:
            return None
        await self.lock_colony_for_write(colony_id)

        model = await self._session.scalar(
            select(WorkerRunModel).where(WorkerRunModel.id == worker_id).with_for_update()
        )
        if model is None or model.status is not WorkerStatus.QUEUED:
            return None
        model.status = WorkerStatus.RUNNING
        model.started_at = utc_now()
        await self.set_session_status(
            model.worker_session_id,
            SessionStatus.RUNNING,
            cursor={"iteration": 0, "phase": "running"},
        )
        await self._session.flush()
        return self._worker_read(model)

    async def finish_worker(
        self,
        session_id: UUID,
        status: WorkerStatus,
        report: Mapping[str, object] | None = None,
        error: Mapping[str, object] | None = None,
    ) -> WorkerRead | None:
        colony_id = await self._session.scalar(
            select(WorkerRunModel.colony_id).where(WorkerRunModel.worker_session_id == session_id)
        )
        if colony_id is None:
            return None
        await self.lock_colony_for_write(colony_id)

        model = await self._session.scalar(
            select(WorkerRunModel)
            .where(WorkerRunModel.worker_session_id == session_id)
            .with_for_update()
        )
        if model is None:
            return None
        model.status = status
        model.report = dict(report) if report is not None else None
        model.error = dict(error) if error is not None else None
        model.ended_at = utc_now()
        session_status = (
            SessionStatus.COMPLETED
            if status in {WorkerStatus.COMPLETED, WorkerStatus.PARTIAL}
            else SessionStatus.FAILED
        )
        await self.set_session_status(model.worker_session_id, session_status)
        await self._session.flush()
        return self._worker_read(model)

    async def upsert_tracker(
        self, colony_id: UUID, session_id: UUID, payload: TrackerUpsert
    ) -> TrackerEntryRead:
        await self.lock_colony_for_write(colony_id)

        model = await self._session.scalar(
            select(TrackerEntryModel)
            .where(
                TrackerEntryModel.colony_id == colony_id,
                TrackerEntryModel.namespace == payload.namespace,
                TrackerEntryModel.entry_key == payload.entry_key,
            )
            .with_for_update()
        )
        if model is None:
            if payload.expected_version is not None:
                raise TrackerVersionConflictError("Tracker entry does not exist")
            model = TrackerEntryModel(
                colony_id=colony_id,
                namespace=payload.namespace,
                entry_key=payload.entry_key,
                status=payload.status,
                data=payload.data,
                version=1,
                updated_by_session_id=session_id,
            )
            self._session.add(model)
        else:
            if payload.expected_version is not None and model.version != payload.expected_version:
                raise TrackerVersionConflictError(
                    f"Expected tracker version {payload.expected_version}, found {model.version}"
                )
            model.status = payload.status
            model.data = cast(dict[str, object], payload.data)
            model.version += 1
            model.updated_by_session_id = session_id
            model.updated_at = utc_now()
        await self._session.flush()
        return self._tracker_read(model)

    async def list_tracker(
        self, colony_id: UUID, namespace: str | None = None
    ) -> list[TrackerEntryRead]:
        statement = select(TrackerEntryModel).where(TrackerEntryModel.colony_id == colony_id)
        if namespace is not None:
            statement = statement.where(TrackerEntryModel.namespace == namespace)
        models = (
            await self._session.scalars(
                statement.order_by(TrackerEntryModel.namespace, TrackerEntryModel.entry_key)
            )
        ).all()
        return [self._tracker_read(model) for model in models]

    async def create_task_item(
        self, colony_id: UUID, session_id: UUID, payload: TaskItemCreate
    ) -> TaskItemRead:
        await self.lock_colony_for_write(colony_id)

        model = TaskItemModel(
            colony_id=colony_id,
            session_id=session_id,
            parent_id=payload.parent_id,
            title=payload.title,
            description=payload.description,
            position=payload.position,
            metadata_=payload.metadata,
        )
        self._session.add(model)
        await self._session.flush()
        return self._task_read(model)

    async def update_task_status(
        self, task_id: UUID, status: TaskItemStatus
    ) -> TaskItemRead | None:
        colony_id = await self._session.scalar(
            select(TaskItemModel.colony_id).where(TaskItemModel.id == task_id)
        )
        if colony_id is None:
            return None
        await self.lock_colony_for_write(colony_id)

        model = await self._session.scalar(
            select(TaskItemModel).where(TaskItemModel.id == task_id).with_for_update()
        )
        if model is None:
            return None
        model.status = status
        model.updated_at = utc_now()
        await self._session.flush()
        return self._task_read(model)

    async def list_tasks(self, colony_id: UUID) -> list[TaskItemRead]:
        models = (
            await self._session.scalars(
                select(TaskItemModel)
                .where(TaskItemModel.colony_id == colony_id)
                .order_by(TaskItemModel.position, TaskItemModel.created_at)
            )
        ).all()
        return [self._task_read(model) for model in models]

    async def append_event(
        self,
        colony_id: UUID,
        event_type: str,
        *,
        session_id: UUID | None = None,
        worker_run_id: UUID | None = None,
        payload: Mapping[str, object] | None = None,
    ) -> ColonyEventRead | None:
        await self.lock_colony_for_write(colony_id)

        colony = await self._session.scalar(
            select(ColonyModel).where(ColonyModel.id == colony_id).with_for_update()
        )
        if colony is None:
            return None
        sequence = await self._session.scalar(
            select(func.coalesce(func.max(ColonyEventModel.sequence), 0) + 1).where(
                ColonyEventModel.colony_id == colony_id
            )
        )
        if sequence is None:
            raise RuntimeError(f"Could not allocate event sequence for colony {colony_id}")
        model = ColonyEventModel(
            colony_id=colony_id,
            session_id=session_id,
            worker_run_id=worker_run_id,
            sequence=sequence,
            type=event_type,
            payload=dict(payload or {}),
        )
        self._session.add(model)
        await self._session.flush()
        return self._event_read(model)

    async def list_events_after(
        self, colony_id: UUID, sequence: int
    ) -> list[ColonyEventRead] | None:
        if await self._session.get(ColonyModel, colony_id) is None:
            return None
        models = (
            await self._session.scalars(
                select(ColonyEventModel)
                .where(
                    ColonyEventModel.colony_id == colony_id,
                    ColonyEventModel.sequence > sequence,
                )
                .order_by(ColonyEventModel.sequence)
            )
        ).all()
        return [self._event_read(model) for model in models]

    @staticmethod
    def _colony_read(model: ColonyModel, queen_session_id: UUID | None) -> ColonyRead:
        return ColonyRead(
            id=model.id,
            name=model.name,
            description=model.description,
            status=model.status,
            queen_profile=model.queen_profile,
            model=model.model,
            settings=JSON_OBJECT.validate_python(model.settings),
            queen_session_id=queen_session_id,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

    @staticmethod
    def _session_read(model: AgentSessionModel) -> SessionRead:
        return SessionRead(
            id=model.id,
            colony_id=model.colony_id,
            parent_session_id=model.parent_session_id,
            actor_type=cast(ActorType, model.actor_type),
            status=model.status,
            park_reason=model.park_reason,
            task=JSON_OBJECT.validate_python(model.task),
            cursor=JSON_OBJECT.validate_python(model.cursor),
            budget=JSON_OBJECT.validate_python(model.budget),
            usage=JSON_OBJECT.validate_python(model.usage),
            created_at=model.created_at,
            updated_at=model.updated_at,
            ended_at=model.ended_at,
        )

    @staticmethod
    def _message_read(model: ConversationMessageModel) -> MessageRead:
        return MessageRead(
            id=model.id,
            session_id=model.session_id,
            sequence=model.sequence,
            role=model.role,
            content=model.content,
            tool_call_id=model.tool_call_id,
            tool_calls=JSON_OBJECTS.validate_python(model.tool_calls),
            metadata=JSON_OBJECT.validate_python(model.metadata_),
            created_at=model.created_at,
        )

    @staticmethod
    def _worker_read(model: WorkerRunModel) -> WorkerRead:
        return WorkerRead(
            id=model.id,
            colony_id=model.colony_id,
            queen_session_id=model.queen_session_id,
            worker_session_id=model.worker_session_id,
            status=model.status,
            task=model.task,
            input=JSON_OBJECT.validate_python(model.input),
            report=JSON_OBJECT.validate_python(model.report) if model.report is not None else None,
            error=JSON_OBJECT.validate_python(model.error) if model.error is not None else None,
            timeout_seconds=model.timeout_seconds,
            queued_at=model.queued_at,
            started_at=model.started_at,
            ended_at=model.ended_at,
        )

    @staticmethod
    def _tracker_read(model: TrackerEntryModel) -> TrackerEntryRead:
        return TrackerEntryRead(
            id=model.id,
            colony_id=model.colony_id,
            namespace=model.namespace,
            entry_key=model.entry_key,
            status=model.status,
            data=JSON_OBJECT.validate_python(model.data),
            version=model.version,
            updated_by_session_id=model.updated_by_session_id,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

    @staticmethod
    def _task_read(model: TaskItemModel) -> TaskItemRead:
        return TaskItemRead(
            id=model.id,
            colony_id=model.colony_id,
            session_id=model.session_id,
            parent_id=model.parent_id,
            title=model.title,
            description=model.description,
            status=model.status,
            position=model.position,
            assigned_worker_id=model.assigned_worker_id,
            metadata=JSON_OBJECT.validate_python(model.metadata_),
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

    @staticmethod
    def _event_read(model: ColonyEventModel) -> ColonyEventRead:
        return ColonyEventRead(
            id=model.id,
            colony_id=model.colony_id,
            session_id=model.session_id,
            worker_run_id=model.worker_run_id,
            sequence=model.sequence,
            type=model.type,
            payload=JSON_OBJECT.validate_python(model.payload),
            created_at=model.created_at,
        )


__all__ = ["ColonyRepository", "TrackerVersionConflictError", "colony_lock_key"]
