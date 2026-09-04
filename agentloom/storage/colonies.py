"""File-backed persistence for Colony aggregates."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import JsonValue, TypeAdapter

from agentloom.colony.message_safety import sanitize_json, sanitize_text
from agentloom.colony.schemas import (
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
from agentloom.llm.base import LLMMessage
from agentloom.runtime.states import ColonyStatus, SessionStatus, TaskItemStatus, WorkerStatus
from agentloom.storage.base import (
    append_json_line,
    atomic_write_json,
    read_json,
    read_json_lines,
    utc_now,
)
from agentloom.storage.tracker import SQLiteTrackerStore

JSON_OBJECT = TypeAdapter(dict[str, JsonValue])
JSON_OBJECTS = TypeAdapter(list[dict[str, JsonValue]])


def default_colony_settings() -> dict[str, JsonValue]:
    """Return independent, bounded Colony defaults."""

    return {
        "max_concurrent_workers": 4,
        "worker_max_turns": 8,
        "worker_timeout_seconds": 600,
        "max_tool_calls": 100,
    }


class LocalColonyStore:
    """Persist Colony state below one local application data directory."""

    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()
        self._colonies = self.root / "colonies"
        self._trash = self.root / "trash"
        self._tracker = SQLiteTrackerStore()
        self._locks: dict[UUID, asyncio.Lock] = {}
        self._root_lock = asyncio.Lock()

    async def initialize(self) -> None:
        """Create and validate the writable storage root."""

        await asyncio.to_thread(self._initialize_sync)

    async def close(self) -> None:
        """Close the store; operations use no persistent file handles."""

    async def recover_interrupted(self) -> tuple[list[UUID], list[UUID]]:
        """Requeue interrupted workers and queens, returning runnable identifiers."""

        worker_ids: list[UUID] = []
        queen_ids: list[UUID] = []
        for colony in await self.list_colonies():
            async with self._lock(colony.id):
                workers, queens = await asyncio.to_thread(self._recover_colony_sync, colony.id)
                worker_ids.extend(workers)
                queen_ids.extend(queens)
        return worker_ids, queen_ids

    async def create(
        self,
        name: str,
        description: str,
        queen_profile: str,
        model: str,
        settings: Mapping[str, object],
    ) -> tuple[ColonyRead, SessionRead]:
        async with self._root_lock:
            merged = default_colony_settings()
            merged.update(JSON_OBJECT.validate_python(dict(settings)))
            now = utc_now()
            colony_id = uuid4()
            queen_id = uuid4()
            colony = ColonyRead(
                id=colony_id,
                name=name,
                description=description,
                status=ColonyStatus.ACTIVE,
                queen_profile=queen_profile,
                model=model,
                settings=merged,
                queen_session_id=queen_id,
                created_at=now,
                updated_at=now,
            )
            queen = SessionRead(
                id=queen_id,
                colony_id=colony_id,
                parent_session_id=None,
                actor_type="queen",
                status=SessionStatus.IDLE,
                park_reason=None,
                task={},
                cursor={"iteration": 0, "phase": "idle"},
                budget=merged,
                usage={"input_tokens": 0, "output_tokens": 0, "tool_calls": 0},
                created_at=now,
                updated_at=now,
                ended_at=None,
            )
            await asyncio.to_thread(self._create_sync, colony, queen)
            await self._tracker.initialize(self._tracker_path(colony_id))
            return colony, queen

    async def list_colonies(self) -> list[ColonyRead]:
        return await asyncio.to_thread(self._list_colonies_sync)

    async def delete_colony(self, colony_id: UUID) -> bool:
        async with self._lock(colony_id):
            return await asyncio.to_thread(self._delete_colony_sync, colony_id)

    async def get(self, colony_id: UUID) -> ColonyRead | None:
        return await asyncio.to_thread(self._get_colony_sync, colony_id)

    async def rename_colony(self, colony_id: UUID, name: str) -> bool:
        async with self._lock(colony_id):
            colony = await asyncio.to_thread(self._get_colony_sync, colony_id)
            if colony is None:
                return False
            updated = colony.model_copy(update={"name": name, "updated_at": utc_now()})
            await asyncio.to_thread(self._write_model, self._metadata_path(colony_id), updated)
            return True

    async def get_session(self, session_id: UUID, *, lock: bool = False) -> SessionRead | None:
        del lock
        located = await asyncio.to_thread(self._find_session_sync, session_id)
        return located[1] if located is not None else None

    async def get_queen_session(self, colony_id: UUID) -> SessionRead | None:
        colony = await self.get(colony_id)
        if colony is None or colony.queen_session_id is None:
            return None
        return await asyncio.to_thread(self._read_session_sync, colony_id, colony.queen_session_id)

    async def set_session_status(
        self,
        session_id: UUID,
        status: SessionStatus,
        *,
        park_reason: str | None = None,
        cursor: Mapping[str, object] | None = None,
        usage: Mapping[str, object] | None = None,
    ) -> bool:
        located = await asyncio.to_thread(self._find_session_sync, session_id)
        if located is None:
            return False
        colony_id, _ = located
        async with self._lock(colony_id):
            current = await asyncio.to_thread(self._read_session_sync, colony_id, session_id)
            if current is None:
                return False
            changes: dict[str, object] = {
                "status": status,
                "park_reason": park_reason,
                "updated_at": utc_now(),
            }
            if cursor is not None:
                changes["cursor"] = JSON_OBJECT.validate_python(dict(cursor))
            if usage is not None:
                changes["usage"] = JSON_OBJECT.validate_python(dict(usage))
            if status in {
                SessionStatus.COMPLETED,
                SessionStatus.FAILED,
                SessionStatus.CANCELLED,
            }:
                changes["ended_at"] = utc_now()
            updated = current.model_copy(update=changes)
            await asyncio.to_thread(
                self._write_model,
                self._session_meta_path(colony_id, session_id),
                updated,
            )
            return True

    async def append_message(
        self,
        session_id: UUID,
        message: LLMMessage,
        *,
        message_id: UUID | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> MessageRead | None:
        located = await asyncio.to_thread(self._find_session_sync, session_id)
        if located is None:
            return None
        colony_id, _ = located
        async with self._lock(colony_id):
            return await asyncio.to_thread(
                self._append_message_sync,
                colony_id,
                session_id,
                message,
                message_id,
                metadata,
            )

    async def list_messages(self, session_id: UUID) -> list[MessageRead] | None:
        located = await asyncio.to_thread(self._find_session_sync, session_id)
        if located is None:
            return None
        return await asyncio.to_thread(self._list_messages_sync, located[0], session_id)

    async def create_workers(
        self,
        queen_session_id: UUID,
        tasks: Sequence[WorkerTask],
        timeout_seconds: int,
    ) -> list[WorkerRead]:
        located = await asyncio.to_thread(self._find_session_sync, queen_session_id)
        if located is None or located[1].actor_type != "queen":
            return []
        colony_id = located[0]
        async with self._lock(colony_id):
            return await asyncio.to_thread(
                self._create_workers_sync,
                colony_id,
                queen_session_id,
                tasks,
                timeout_seconds,
            )

    async def list_workers(self, colony_id: UUID) -> list[WorkerRead]:
        return await asyncio.to_thread(self._list_workers_sync, colony_id)

    async def get_worker_for_session(self, session_id: UUID) -> WorkerRead | None:
        return await asyncio.to_thread(self._get_worker_for_session_sync, session_id)

    async def mark_worker_running(self, worker_id: UUID) -> WorkerRead | None:
        located = await asyncio.to_thread(self._find_worker_sync, worker_id)
        if located is None:
            return None
        colony_id, _ = located
        async with self._lock(colony_id):
            return await asyncio.to_thread(self._mark_worker_running_sync, colony_id, worker_id)

    async def finish_worker(
        self,
        session_id: UUID,
        status: WorkerStatus,
        report: Mapping[str, object] | None = None,
        error: Mapping[str, object] | None = None,
    ) -> WorkerRead | None:
        worker = await self.get_worker_for_session(session_id)
        if worker is None:
            return None
        async with self._lock(worker.colony_id):
            return await asyncio.to_thread(
                self._finish_worker_sync,
                worker.colony_id,
                worker.id,
                status,
                report,
                error,
            )

    async def upsert_tracker(
        self,
        colony_id: UUID,
        session_id: UUID,
        payload: TrackerUpsert,
    ) -> TrackerEntryRead:
        async with self._lock(colony_id):
            if await self.get(colony_id) is None:
                raise KeyError(str(colony_id))
            return await self._tracker.upsert(
                self._tracker_path(colony_id), colony_id, session_id, payload
            )

    async def list_tracker(
        self,
        colony_id: UUID,
        namespace: str | None = None,
    ) -> list[TrackerEntryRead]:
        if await self.get(colony_id) is None:
            return []
        return await self._tracker.list(self._tracker_path(colony_id), colony_id, namespace)

    async def create_task_item(
        self,
        colony_id: UUID,
        session_id: UUID,
        payload: TaskItemCreate,
    ) -> TaskItemRead:
        async with self._lock(colony_id):
            return await asyncio.to_thread(self._create_task_sync, colony_id, session_id, payload)

    async def update_task_status(
        self,
        task_id: UUID,
        status: TaskItemStatus,
    ) -> TaskItemRead | None:
        located = await asyncio.to_thread(self._find_task_sync, task_id)
        if located is None:
            return None
        colony_id, session_id, _ = located
        async with self._lock(colony_id):
            return await asyncio.to_thread(
                self._update_task_sync, colony_id, session_id, task_id, status
            )

    async def list_tasks(self, colony_id: UUID) -> list[TaskItemRead]:
        return await asyncio.to_thread(self._list_tasks_sync, colony_id)

    async def append_event(
        self,
        colony_id: UUID,
        event_type: str,
        *,
        session_id: UUID | None = None,
        worker_run_id: UUID | None = None,
        payload: Mapping[str, object] | None = None,
    ) -> ColonyEventRead | None:
        async with self._lock(colony_id):
            if await self.get(colony_id) is None:
                return None
            return await asyncio.to_thread(
                self._append_event_sync,
                colony_id,
                event_type,
                session_id,
                worker_run_id,
                payload,
            )

    async def list_events_after(
        self,
        colony_id: UUID,
        sequence: int,
    ) -> list[ColonyEventRead] | None:
        if await self.get(colony_id) is None:
            return None
        records = await asyncio.to_thread(read_json_lines, self._events_path(colony_id))
        events = [ColonyEventRead.model_validate(record) for record in records]
        return [event for event in events if event.sequence > sequence]

    def _initialize_sync(self) -> None:
        self._colonies.mkdir(parents=True, exist_ok=True)
        self._trash.mkdir(parents=True, exist_ok=True)
        probe = self.root / f".write-test-{uuid4().hex}"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()

    def _create_sync(self, colony: ColonyRead, queen: SessionRead) -> None:
        colony_dir = self._colony_dir(colony.id)
        colony_dir.mkdir(parents=True, exist_ok=False)
        (colony_dir / "sessions").mkdir()
        (colony_dir / "workers").mkdir()
        (colony_dir / "tracker").mkdir()
        (colony_dir / "artifacts").mkdir()
        self._write_model(self._metadata_path(colony.id), colony)
        self._write_session_sync(queen)

    def _list_colonies_sync(self) -> list[ColonyRead]:
        if not self._colonies.exists():
            return []
        colonies = [
            ColonyRead.model_validate(read_json(path))
            for path in self._colonies.glob("*/metadata.json")
        ]
        return sorted(colonies, key=lambda item: item.created_at, reverse=True)

    def _delete_colony_sync(self, colony_id: UUID) -> bool:
        source = self._colony_dir(colony_id)
        metadata = source / "metadata.json"
        if not metadata.is_file():
            return False
        self._trash.mkdir(parents=True, exist_ok=True)
        destination = self._trash / f"{colony_id}-{uuid4().hex}.json"
        metadata.replace(destination)
        return True

    def _get_colony_sync(self, colony_id: UUID) -> ColonyRead | None:
        path = self._metadata_path(colony_id)
        return ColonyRead.model_validate(read_json(path)) if path.is_file() else None

    def _find_session_sync(self, session_id: UUID) -> tuple[UUID, SessionRead] | None:
        if not self._colonies.exists():
            return None
        for colony_dir in self._colonies.iterdir():
            if not (colony_dir / "metadata.json").is_file():
                continue
            path = colony_dir / "sessions" / str(session_id) / "meta.json"
            if path.is_file():
                return UUID(colony_dir.name), SessionRead.model_validate(read_json(path))
        return None

    def _read_session_sync(self, colony_id: UUID, session_id: UUID) -> SessionRead | None:
        path = self._session_meta_path(colony_id, session_id)
        return SessionRead.model_validate(read_json(path)) if path.is_file() else None

    def _write_session_sync(self, session: SessionRead) -> None:
        base = self._session_dir(session.colony_id, session.id)
        (base / "conversations" / "parts").mkdir(parents=True, exist_ok=True)
        (base / "conversations" / "partials").mkdir(parents=True, exist_ok=True)
        (base / "data").mkdir(parents=True, exist_ok=True)
        self._write_model(base / "meta.json", session)

    def _append_message_sync(
        self,
        colony_id: UUID,
        session_id: UUID,
        message: LLMMessage,
        message_id: UUID | None,
        metadata: Mapping[str, object] | None,
    ) -> MessageRead | None:
        if self._read_session_sync(colony_id, session_id) is None:
            return None
        parts = self._parts_dir(colony_id, session_id)
        sequences = [int(path.stem) for path in parts.glob("*.json")]
        sequence = max(sequences, default=0) + 1
        calls = JSON_OBJECTS.validate_python(
            [sanitize_json(call.model_dump(mode="json")) for call in message.tool_calls]
        )
        saved = MessageRead(
            id=message_id or uuid4(),
            session_id=session_id,
            sequence=sequence,
            role=message.role,
            content=sanitize_text(message.content),
            reasoning_content=message.reasoning_content,
            tool_call_id=message.tool_call_id,
            tool_calls=calls,
            metadata=JSON_OBJECT.validate_python(
                sanitize_json(JSON_OBJECT.validate_python(dict(metadata or {})))
            ),
            created_at=utc_now(),
        )
        payload = saved.model_dump(mode="json")
        if saved.reasoning_content is not None:
            payload["reasoning_content"] = saved.reasoning_content
        atomic_write_json(parts / f"{sequence:010d}.json", payload)
        return saved

    def _list_messages_sync(self, colony_id: UUID, session_id: UUID) -> list[MessageRead]:
        return [
            MessageRead.model_validate(read_json(path))
            for path in sorted(self._parts_dir(colony_id, session_id).glob("*.json"))
        ]

    def _create_workers_sync(
        self,
        colony_id: UUID,
        queen_session_id: UUID,
        tasks: Sequence[WorkerTask],
        timeout_seconds: int,
    ) -> list[WorkerRead]:
        now = utc_now()
        workers: list[WorkerRead] = []
        for task in tasks:
            session_id = uuid4()
            worker_id = uuid4()
            session = SessionRead(
                id=session_id,
                colony_id=colony_id,
                parent_session_id=queen_session_id,
                actor_type="worker",
                status=SessionStatus.QUEUED,
                park_reason=None,
                task={"description": task.task, "data": task.data},
                cursor={"iteration": 0, "phase": "queued"},
                budget={"max_turns": 8, "max_tool_calls": 30},
                usage={"input_tokens": 0, "output_tokens": 0, "tool_calls": 0},
                created_at=now,
                updated_at=now,
                ended_at=None,
            )
            worker = WorkerRead(
                id=worker_id,
                colony_id=colony_id,
                queen_session_id=queen_session_id,
                worker_session_id=session_id,
                status=WorkerStatus.QUEUED,
                task=task.task,
                input=task.data,
                report=None,
                error=None,
                timeout_seconds=timeout_seconds,
                queued_at=now,
                started_at=None,
                ended_at=None,
            )
            self._write_session_sync(session)
            self._write_model(self._worker_meta_path(colony_id, worker_id), worker)
            workers.append(worker)
        return workers

    def _list_workers_sync(self, colony_id: UUID) -> list[WorkerRead]:
        directory = self._workers_dir(colony_id)
        if not directory.exists():
            return []
        workers = [
            WorkerRead.model_validate(read_json(path)) for path in directory.glob("*/meta.json")
        ]
        return sorted(workers, key=lambda item: item.queued_at, reverse=True)

    def _get_worker_for_session_sync(self, session_id: UUID) -> WorkerRead | None:
        for colony in self._list_colonies_sync():
            for worker in self._list_workers_sync(colony.id):
                if worker.worker_session_id == session_id:
                    return worker
        return None

    def _find_worker_sync(self, worker_id: UUID) -> tuple[UUID, WorkerRead] | None:
        for colony in self._list_colonies_sync():
            path = self._worker_meta_path(colony.id, worker_id)
            if path.is_file():
                return colony.id, WorkerRead.model_validate(read_json(path))
        return None

    def _mark_worker_running_sync(self, colony_id: UUID, worker_id: UUID) -> WorkerRead | None:
        path = self._worker_meta_path(colony_id, worker_id)
        if not path.is_file():
            return None
        worker = WorkerRead.model_validate(read_json(path))
        if worker.status is not WorkerStatus.QUEUED:
            return None
        now = utc_now()
        updated = worker.model_copy(update={"status": WorkerStatus.RUNNING, "started_at": now})
        self._write_model(path, updated)
        session = self._read_session_sync(colony_id, worker.worker_session_id)
        if session is None:
            raise RuntimeError(f"Worker {worker_id} has no session")
        self._write_session_sync(
            session.model_copy(
                update={
                    "status": SessionStatus.RUNNING,
                    "cursor": {"iteration": 0, "phase": "running"},
                    "updated_at": now,
                }
            )
        )
        return updated

    def _finish_worker_sync(
        self,
        colony_id: UUID,
        worker_id: UUID,
        status: WorkerStatus,
        report: Mapping[str, object] | None,
        error: Mapping[str, object] | None,
    ) -> WorkerRead | None:
        path = self._worker_meta_path(colony_id, worker_id)
        if not path.is_file():
            return None
        worker = WorkerRead.model_validate(read_json(path))
        now = utc_now()
        updated = worker.model_copy(
            update={
                "status": status,
                "report": JSON_OBJECT.validate_python(dict(report)) if report is not None else None,
                "error": JSON_OBJECT.validate_python(dict(error)) if error is not None else None,
                "ended_at": now,
            }
        )
        self._write_model(path, updated)
        session = self._read_session_sync(colony_id, worker.worker_session_id)
        if session is None:
            raise RuntimeError(f"Worker {worker_id} has no session")
        session_status = (
            SessionStatus.COMPLETED
            if status in {WorkerStatus.COMPLETED, WorkerStatus.PARTIAL}
            else SessionStatus.FAILED
        )
        self._write_session_sync(
            session.model_copy(
                update={"status": session_status, "updated_at": now, "ended_at": now}
            )
        )
        return updated

    def _create_task_sync(
        self,
        colony_id: UUID,
        session_id: UUID,
        payload: TaskItemCreate,
    ) -> TaskItemRead:
        if self._read_session_sync(colony_id, session_id) is None:
            raise KeyError(str(session_id))
        now = utc_now()
        item = TaskItemRead(
            id=uuid4(),
            colony_id=colony_id,
            session_id=session_id,
            parent_id=payload.parent_id,
            title=payload.title,
            description=payload.description,
            status=TaskItemStatus.PENDING,
            position=payload.position,
            assigned_worker_id=None,
            metadata=payload.metadata,
            created_at=now,
            updated_at=now,
        )
        tasks = self._read_tasks_sync(colony_id, session_id)
        tasks.append(item)
        self._write_tasks_sync(colony_id, session_id, tasks)
        return item

    def _find_task_sync(self, task_id: UUID) -> tuple[UUID, UUID, TaskItemRead] | None:
        for colony in self._list_colonies_sync():
            sessions_dir = self._sessions_dir(colony.id)
            if not sessions_dir.exists():
                continue
            for session_dir in sessions_dir.iterdir():
                session_id = UUID(session_dir.name)
                for task in self._read_tasks_sync(colony.id, session_id):
                    if task.id == task_id:
                        return colony.id, session_id, task
        return None

    def _update_task_sync(
        self,
        colony_id: UUID,
        session_id: UUID,
        task_id: UUID,
        status: TaskItemStatus,
    ) -> TaskItemRead | None:
        tasks = self._read_tasks_sync(colony_id, session_id)
        updated: TaskItemRead | None = None
        result: list[TaskItemRead] = []
        for task in tasks:
            if task.id == task_id:
                updated = task.model_copy(update={"status": status, "updated_at": utc_now()})
                result.append(updated)
            else:
                result.append(task)
        if updated is not None:
            self._write_tasks_sync(colony_id, session_id, result)
        return updated

    def _list_tasks_sync(self, colony_id: UUID) -> list[TaskItemRead]:
        directory = self._sessions_dir(colony_id)
        if not directory.exists():
            return []
        tasks: list[TaskItemRead] = []
        for session_dir in directory.iterdir():
            tasks.extend(self._read_tasks_sync(colony_id, UUID(session_dir.name)))
        return sorted(tasks, key=lambda item: (item.position, item.created_at))

    def _read_tasks_sync(self, colony_id: UUID, session_id: UUID) -> list[TaskItemRead]:
        path = self._tasks_path(colony_id, session_id)
        if not path.is_file():
            return []
        document = read_json(path)
        values = JSON_OBJECTS.validate_python(document.get("tasks"))
        return [TaskItemRead.model_validate(value) for value in values]

    def _write_tasks_sync(
        self, colony_id: UUID, session_id: UUID, tasks: list[TaskItemRead]
    ) -> None:
        atomic_write_json(
            self._tasks_path(colony_id, session_id),
            {"schema_version": 1, "tasks": [task.model_dump(mode="json") for task in tasks]},
        )

    def _append_event_sync(
        self,
        colony_id: UUID,
        event_type: str,
        session_id: UUID | None,
        worker_run_id: UUID | None,
        payload: Mapping[str, object] | None,
    ) -> ColonyEventRead:
        path = self._events_path(colony_id)
        events = [ColonyEventRead.model_validate(record) for record in read_json_lines(path)]
        sequence = max((event.sequence for event in events), default=0) + 1
        event = ColonyEventRead(
            id=uuid4(),
            colony_id=colony_id,
            session_id=session_id,
            worker_run_id=worker_run_id,
            sequence=sequence,
            type=event_type,
            payload=JSON_OBJECT.validate_python(
                sanitize_json(JSON_OBJECT.validate_python(dict(payload or {})))
            ),
            created_at=utc_now(),
        )
        append_json_line(path, event.model_dump(mode="json"))
        return event

    def _recover_colony_sync(self, colony_id: UUID) -> tuple[list[UUID], list[UUID]]:
        worker_ids: list[UUID] = []
        for worker in self._list_workers_sync(colony_id):
            current = worker
            if worker.status is WorkerStatus.RUNNING:
                current = worker.model_copy(
                    update={"status": WorkerStatus.QUEUED, "started_at": None}
                )
                self._write_model(self._worker_meta_path(colony_id, worker.id), current)
                session = self._read_session_sync(colony_id, worker.worker_session_id)
                if session is not None:
                    self._write_session_sync(
                        session.model_copy(
                            update={"status": SessionStatus.QUEUED, "updated_at": utc_now()}
                        )
                    )
            if current.status is WorkerStatus.QUEUED:
                worker_ids.append(current.id)

        queen_ids: list[UUID] = []
        sessions_dir = self._sessions_dir(colony_id)
        for path in sessions_dir.glob("*/meta.json"):
            session = SessionRead.model_validate(read_json(path))
            if session.actor_type != "queen":
                continue
            current = session
            if session.status is SessionStatus.RUNNING:
                current = session.model_copy(
                    update={"status": SessionStatus.QUEUED, "updated_at": utc_now()}
                )
                self._write_model(path, current)
            if current.status is SessionStatus.QUEUED:
                queen_ids.append(current.id)
        return worker_ids, queen_ids

    def _lock(self, colony_id: UUID) -> asyncio.Lock:
        return self._locks.setdefault(colony_id, asyncio.Lock())

    def _colony_dir(self, colony_id: UUID) -> Path:
        return self._colonies / str(colony_id)

    def _metadata_path(self, colony_id: UUID) -> Path:
        return self._colony_dir(colony_id) / "metadata.json"

    def _sessions_dir(self, colony_id: UUID) -> Path:
        return self._colony_dir(colony_id) / "sessions"

    def _session_dir(self, colony_id: UUID, session_id: UUID) -> Path:
        return self._sessions_dir(colony_id) / str(session_id)

    def _session_meta_path(self, colony_id: UUID, session_id: UUID) -> Path:
        return self._session_dir(colony_id, session_id) / "meta.json"

    def _parts_dir(self, colony_id: UUID, session_id: UUID) -> Path:
        return self._session_dir(colony_id, session_id) / "conversations" / "parts"

    def _tasks_path(self, colony_id: UUID, session_id: UUID) -> Path:
        return self._session_dir(colony_id, session_id) / "tasks.json"

    def _workers_dir(self, colony_id: UUID) -> Path:
        return self._colony_dir(colony_id) / "workers"

    def _worker_meta_path(self, colony_id: UUID, worker_id: UUID) -> Path:
        return self._workers_dir(colony_id) / str(worker_id) / "meta.json"

    def _tracker_path(self, colony_id: UUID) -> Path:
        return self._colony_dir(colony_id) / "tracker" / "tracker.db"

    def _events_path(self, colony_id: UUID) -> Path:
        return self._colony_dir(colony_id) / "events.jsonl"

    @staticmethod
    def _write_model(
        path: Path,
        model: ColonyRead | SessionRead | MessageRead | WorkerRead,
    ) -> None:
        atomic_write_json(path, model.model_dump(mode="json"))


__all__ = ["LocalColonyStore", "default_colony_settings"]
