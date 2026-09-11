"""File-backed persistence for Colony aggregates."""

from __future__ import annotations

import asyncio
import json
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import JsonValue, TypeAdapter

from agentloom.colony.message_safety import redact_json, sanitize_json, sanitize_text
from agentloom.colony.schemas import (
    ColonyEventRead,
    ColonyForkCreate,
    ColonyRead,
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
    WorkerTask,
)
from agentloom.context.schemas import CompactionCheckpoint
from agentloom.llm.base import LLMMessage
from agentloom.runtime.states import ColonyStatus, SessionStatus, TaskItemStatus, WorkerStatus
from agentloom.storage.base import (
    append_json_line,
    atomic_write_json,
    read_json,
    read_json_lines,
    utc_now,
)
from agentloom.storage.queens import LocalQueenStore
from agentloom.storage.settings import LocalUserSettingsStore
from agentloom.storage.tracker import SQLiteTrackerStore
from agentloom.user_settings import (
    UserLLMRuntimeConfig,
    UserSettingsRead,
    UserSettingsUpdate,
)

JSON_OBJECT = TypeAdapter(dict[str, JsonValue])
JSON_OBJECTS = TypeAdapter(list[dict[str, JsonValue]])


@dataclass(frozen=True)
class SessionLocation:
    base: Path
    session: SessionRead
    lock_id: UUID


def default_colony_settings() -> dict[str, JsonValue]:
    """Return independent, bounded Colony defaults."""

    return {
        "max_concurrent_workers": 4,
        "worker_max_turns": 8,
        "worker_timeout_seconds": 600,
        "max_tool_calls": 100,
        "grace_turns": 1,
        "max_context_tokens": 128_000,
        "compaction_buffer_tokens": 8_000,
        "compaction_buffer_ratio": 0.4,
        "compaction_summary_max_tokens": 8_192,
        "max_tool_result_chars": 20_000,
        "max_verbatim_user_messages": 40,
    }


class LocalColonyStore:
    """Persist Colony state below one local application data directory."""

    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()
        self._colonies = self.root / "colonies"
        self._trash = self.root / "trash"
        self._tracker = SQLiteTrackerStore()
        self._queens = LocalQueenStore(self.root)
        self._user_settings = LocalUserSettingsStore(self.root)
        self._locks: dict[UUID, asyncio.Lock] = {}
        self._root_lock = asyncio.Lock()

    async def initialize(self) -> None:
        """Create and validate the writable storage root."""

        await asyncio.to_thread(self._initialize_sync)
        await self._queens.initialize()
        await self._user_settings.initialize()

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
        for queen in await self._queens.list():
            for session in await asyncio.to_thread(self._list_dm_sessions_sync, queen.id):
                if session.status is SessionStatus.RUNNING:
                    session = session.model_copy(
                        update={"status": SessionStatus.QUEUED, "updated_at": utc_now()}
                    )
                    await asyncio.to_thread(self._write_session_sync, session)
                if session.status is SessionStatus.QUEUED:
                    queen_ids.append(session.id)
        return worker_ids, queen_ids

    async def create(
        self,
        name: str,
        description: str,
        queen_id: str,
        settings: Mapping[str, object],
    ) -> tuple[ColonyRead, SessionRead]:
        queen_identity = await self._queens.get(queen_id)
        if queen_identity is None:
            raise KeyError(queen_id)
        llm = await self._require_llm_settings()
        async with self._root_lock:
            merged = default_colony_settings()
            merged["max_context_tokens"] = llm.max_context_tokens
            merged.update(JSON_OBJECT.validate_python(dict(settings)))
            now = utc_now()
            colony_id = uuid4()
            queen_session_id = uuid4()
            colony = ColonyRead(
                id=colony_id,
                name=name,
                description=description,
                status=ColonyStatus.ACTIVE,
                queen_id=queen_id,
                model=llm.model,
                settings=merged,
                queen_session_id=queen_session_id,
                created_at=now,
                updated_at=now,
            )
            queen = SessionRead(
                id=queen_session_id,
                colony_id=colony_id,
                queen_id=queen_id,
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
            await self._queens.add_session_reference(queen_id, queen.id, colony.id)
            await self._tracker.initialize(self._tracker_path(colony_id))
            return colony, queen

    async def list_colonies(self) -> list[ColonyRead]:
        return await asyncio.to_thread(self._list_colonies_sync)

    async def create_queen(self, payload: QueenCreate) -> QueenRead:
        return await self._queens.create(payload)

    async def list_queens(self) -> list[QueenRead]:
        return await self._queens.list()

    async def get_queen(self, queen_id: str) -> QueenRead | None:
        return await self._queens.get(queen_id)

    async def get_user_settings(self) -> UserSettingsRead:
        return await self._user_settings.get()

    async def update_user_settings(self, payload: UserSettingsUpdate) -> UserSettingsRead:
        return await self._user_settings.update(payload)

    async def get_user_llm_runtime_config(self) -> UserLLMRuntimeConfig | None:
        return await self._user_settings.get_runtime_config()

    async def list_queen_sessions(self, queen_id: str) -> list[SessionRead]:
        sessions = await asyncio.to_thread(self._list_dm_sessions_sync, queen_id)
        for colony in await self.list_colonies():
            if colony.queen_id != queen_id or colony.queen_session_id is None:
                continue
            session = await self.get_session(colony.queen_session_id)
            if session is not None:
                sessions.append(session)
        return sorted(sessions, key=lambda item: item.created_at, reverse=True)

    async def create_dm_session(self, queen_id: str) -> SessionRead:
        queen = await self._queens.get(queen_id)
        if queen is None:
            raise KeyError(queen_id)
        async with self._root_lock:
            settings = default_colony_settings()
            llm = await self._user_settings.get_runtime_config()
            if llm is not None:
                settings["max_context_tokens"] = llm.max_context_tokens
            now = utc_now()
            session = SessionRead(
                id=uuid4(),
                colony_id=None,
                queen_id=queen_id,
                parent_session_id=None,
                actor_type="queen",
                session_kind="dm",
                operating_phase="independent",
                status=SessionStatus.IDLE,
                park_reason=None,
                task={},
                cursor={"iteration": 0, "phase": "idle"},
                budget=settings,
                usage={"input_tokens": 0, "output_tokens": 0, "tool_calls": 0},
                created_at=now,
                updated_at=now,
                ended_at=None,
            )
            await asyncio.to_thread(self._write_session_sync, session)
            return session

    async def set_colony_suggestion(
        self, session_id: UUID, suggestion: ColonySuggestion | None
    ) -> SessionRead | None:
        located = await asyncio.to_thread(self._find_session_sync, session_id)
        if located is None:
            return None
        async with self._lock(located.lock_id):
            current = await asyncio.to_thread(self._read_session_at_sync, located.base)
            if current is None:
                return None
            updated = current.model_copy(
                update={"pending_colony_suggestion": suggestion, "updated_at": utc_now()}
            )
            await asyncio.to_thread(self._write_model, located.base / "meta.json", updated)
            return updated

    async def fork_dm_session(
        self, source_session_id: UUID, payload: ColonyForkCreate
    ) -> tuple[ColonyRead, SessionRead]:
        async with self._root_lock:
            located = await asyncio.to_thread(self._find_session_sync, source_session_id)
            if located is None:
                raise KeyError(str(source_session_id))
            source = located.session
            suggestion = source.pending_colony_suggestion
            if source.session_kind != "dm" or source.operating_phase != "independent":
                raise ValueError("只有独立 Queen 会话可以创建 Colony")
            if source.forked_to_colony_id is not None or source.status is SessionStatus.FORKED:
                raise ValueError("该会话已经创建过 Colony")
            if source.status is not SessionStatus.IDLE:
                raise ValueError("Queen 当前仍在运行，请等待本轮完成后再创建 Colony")
            if suggestion is None or suggestion.id != payload.suggestion_id:
                raise ValueError("Colony 建议不存在或已失效")
            if suggestion.status != "pending":
                raise ValueError("Colony 建议已经处理")
            queen = await self._queens.get(source.queen_id)
            if queen is None:
                raise KeyError(source.queen_id)
            llm = await self._require_llm_settings()

            now = utc_now()
            colony_id = uuid4()
            target_session_id = uuid4()
            colony = ColonyRead(
                id=colony_id,
                name=payload.name,
                description=payload.description,
                status=ColonyStatus.ACTIVE,
                queen_id=source.queen_id,
                model=llm.model,
                settings=source.budget,
                queen_session_id=target_session_id,
                source_session_id=source.id,
                created_at=now,
                updated_at=now,
            )
            target = source.model_copy(
                update={
                    "id": target_session_id,
                    "colony_id": colony_id,
                    "session_kind": "colony",
                    "operating_phase": "colony",
                    "pending_colony_suggestion": None,
                    "forked_to_colony_id": None,
                    "forked_to_session_id": None,
                    "status": SessionStatus.IDLE,
                    "cursor": {"iteration": 0, "phase": "idle"},
                    "updated_at": now,
                    "ended_at": None,
                }
            )
            await asyncio.to_thread(self._fork_dm_session_sync, located.base, colony, target)
            await self._tracker.initialize(self._tracker_path(colony_id))
            await self._queens.add_session_reference(source.queen_id, target.id, colony.id)
            accepted = suggestion.model_copy(update={"status": "accepted"})
            locked_source = source.model_copy(
                update={
                    "pending_colony_suggestion": accepted,
                    "forked_to_colony_id": colony.id,
                    "forked_to_session_id": target.id,
                    "status": SessionStatus.FORKED,
                    "updated_at": utc_now(),
                    "ended_at": utc_now(),
                }
            )
            await asyncio.to_thread(self._write_model, located.base / "meta.json", locked_source)
            return colony, target

    async def delete_colony(self, colony_id: UUID) -> bool:
        async with self._lock(colony_id):
            colony = await self.get(colony_id)
            deleted = await asyncio.to_thread(self._delete_colony_sync, colony_id)
            if deleted and colony is not None and colony.queen_session_id is not None:
                await self._queens.remove_session_reference(
                    colony.queen_id, colony.queen_session_id
                )
            return deleted

    async def delete_session(self, session_id: UUID) -> bool:
        located = await asyncio.to_thread(self._find_session_sync, session_id)
        if located is None:
            return False
        if located.session.colony_id is not None:
            raise ValueError("Colony 会话必须通过 Colony 删除入口删除")
        if located.session.status in {SessionStatus.QUEUED, SessionStatus.RUNNING}:
            raise ValueError("会话仍在运行，无法删除")
        async with self._lock(located.lock_id):
            return await asyncio.to_thread(
                self._delete_dm_session_sync,
                located.base,
                session_id,
            )

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
        return located.session if located is not None else None

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
        async with self._lock(located.lock_id):
            current = await asyncio.to_thread(self._read_session_at_sync, located.base)
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
                SessionStatus.FORKED,
                SessionStatus.COMPLETED,
                SessionStatus.FAILED,
                SessionStatus.CANCELLED,
            }:
                changes["ended_at"] = utc_now()
            updated = current.model_copy(update=changes)
            await asyncio.to_thread(
                self._write_model,
                located.base / "meta.json",
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
        async with self._lock(located.lock_id):
            return await asyncio.to_thread(
                self._append_message_sync,
                located.base,
                located.session,
                message,
                message_id,
                metadata,
            )

    async def list_messages(self, session_id: UUID) -> list[MessageRead] | None:
        located = await asyncio.to_thread(self._find_session_sync, session_id)
        if located is None:
            return None
        return await asyncio.to_thread(self._list_messages_at_sync, located.base)

    async def get_compaction_checkpoint(self, session_id: UUID) -> CompactionCheckpoint | None:
        located = await asyncio.to_thread(self._find_session_sync, session_id)
        if located is None:
            return None
        return await asyncio.to_thread(self._get_compaction_checkpoint_at_sync, located.base)

    async def save_compaction_checkpoint(
        self, session_id: UUID, checkpoint: CompactionCheckpoint
    ) -> None:
        located = await asyncio.to_thread(self._find_session_sync, session_id)
        if located is None:
            raise KeyError(str(session_id))
        async with self._lock(located.lock_id):
            await asyncio.to_thread(
                atomic_write_json,
                located.base / "context" / "compaction.json",
                checkpoint.model_dump(mode="json"),
            )

    async def write_tool_spillover(self, session_id: UUID, tool_name: str, value: JsonValue) -> str:
        located = await asyncio.to_thread(self._find_session_sync, session_id)
        if located is None:
            raise KeyError(str(session_id))
        async with self._lock(located.lock_id):
            return await asyncio.to_thread(
                self._write_tool_spillover_sync,
                located.base,
                tool_name,
                value,
            )

    async def read_tool_spillover(
        self,
        session_id: UUID,
        filename: str,
        offset: int,
        limit: int,
    ) -> dict[str, JsonValue]:
        located = await asyncio.to_thread(self._find_session_sync, session_id)
        if located is None:
            raise KeyError(str(session_id))
        return await asyncio.to_thread(
            self._read_tool_spillover_sync,
            located.base,
            filename,
            offset,
            limit,
        )

    async def create_workers(
        self,
        queen_session_id: UUID,
        tasks: Sequence[WorkerTask],
        timeout_seconds: int,
    ) -> list[WorkerRead]:
        located = await asyncio.to_thread(self._find_session_sync, queen_session_id)
        if (
            located is None
            or located.session.actor_type != "queen"
            or located.session.colony_id is None
        ):
            return []
        colony_id = located.session.colony_id
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

    async def get_worker(self, worker_id: UUID) -> WorkerRead | None:
        located = await asyncio.to_thread(self._find_worker_sync, worker_id)
        return located[1] if located is not None else None

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

    async def finish_worker_if_active(
        self,
        session_id: UUID,
        status: WorkerStatus,
        report: Mapping[str, object] | None = None,
        error: Mapping[str, object] | None = None,
    ) -> WorkerRead | None:
        """Move an active Worker to a terminal state without overwriting a winner."""

        worker = await self.get_worker_for_session(session_id)
        if worker is None:
            return None
        async with self._lock(worker.colony_id):
            return await asyncio.to_thread(
                self._finish_worker_if_active_sync,
                worker.colony_id,
                worker.id,
                status,
                report,
                error,
            )

    async def attach_worker_report_if_missing(
        self,
        session_id: UUID,
        report: Mapping[str, object],
    ) -> WorkerRead | None:
        """Attach one synthetic report to an already terminal Worker."""

        worker = await self.get_worker_for_session(session_id)
        if worker is None:
            return None
        async with self._lock(worker.colony_id):
            return await asyncio.to_thread(
                self._attach_worker_report_if_missing_sync,
                worker.colony_id,
                worker.id,
                report,
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

    async def append_session_event(
        self,
        session_id: UUID,
        event_type: str,
        *,
        worker_run_id: UUID | None = None,
        payload: Mapping[str, object] | None = None,
    ) -> ColonyEventRead | None:
        located = await asyncio.to_thread(self._find_session_sync, session_id)
        if located is None:
            return None
        if located.session.colony_id is not None:
            return await self.append_event(
                located.session.colony_id,
                event_type,
                session_id=session_id,
                worker_run_id=worker_run_id,
                payload=payload,
            )
        async with self._lock(located.lock_id):
            return await asyncio.to_thread(
                self._append_event_at_sync,
                located.base / "events.jsonl",
                None,
                event_type,
                session_id,
                worker_run_id,
                payload,
            )

    async def list_session_events_after(
        self, session_id: UUID, sequence: int
    ) -> list[ColonyEventRead] | None:
        located = await asyncio.to_thread(self._find_session_sync, session_id)
        if located is None:
            return None
        path = (
            self._events_path(located.session.colony_id)
            if located.session.colony_id is not None
            else located.base / "events.jsonl"
        )
        records = await asyncio.to_thread(read_json_lines, path)
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

    def _delete_dm_session_sync(self, source: Path, session_id: UUID) -> bool:
        if not (source / "meta.json").is_file():
            return False
        self._trash.mkdir(parents=True, exist_ok=True)
        destination = self._trash / f"session-{session_id}-{uuid4().hex}"
        source.replace(destination)
        return True

    async def _require_llm_settings(self) -> UserLLMRuntimeConfig:
        config = await self._user_settings.get_runtime_config()
        if config is None:
            raise RuntimeError("全局 LLM 设置尚未配置")
        return config

    def _get_colony_sync(self, colony_id: UUID) -> ColonyRead | None:
        path = self._metadata_path(colony_id)
        return ColonyRead.model_validate(read_json(path)) if path.is_file() else None

    def _find_session_sync(self, session_id: UUID) -> SessionLocation | None:
        if self._colonies.exists():
            for colony_dir in self._colonies.iterdir():
                if not (colony_dir / "metadata.json").is_file():
                    continue
                base = colony_dir / "sessions" / str(session_id)
                path = base / "meta.json"
                if path.is_file():
                    return SessionLocation(
                        base=base,
                        session=SessionRead.model_validate(read_json(path)),
                        lock_id=UUID(colony_dir.name),
                    )
        queens_dir = self.root / "queens"
        if queens_dir.exists():
            for queen_dir in queens_dir.iterdir():
                base = queen_dir / "sessions" / str(session_id)
                path = base / "meta.json"
                if path.is_file():
                    return SessionLocation(
                        base=base,
                        session=SessionRead.model_validate(read_json(path)),
                        lock_id=session_id,
                    )
        return None

    def _list_dm_sessions_sync(self, queen_id: str) -> list[SessionRead]:
        directory = self.root / "queens" / queen_id / "sessions"
        if not directory.is_dir():
            return []
        return [
            SessionRead.model_validate(read_json(path)) for path in directory.glob("*/meta.json")
        ]

    def _read_session_sync(self, colony_id: UUID, session_id: UUID) -> SessionRead | None:
        path = self._session_meta_path(colony_id, session_id)
        return SessionRead.model_validate(read_json(path)) if path.is_file() else None

    @staticmethod
    def _read_session_at_sync(base: Path) -> SessionRead | None:
        path = base / "meta.json"
        return SessionRead.model_validate(read_json(path)) if path.is_file() else None

    def _fork_dm_session_sync(
        self,
        source_base: Path,
        colony: ColonyRead,
        target: SessionRead,
    ) -> None:
        final_dir = self._colony_dir(colony.id)
        # Keep the staging name short so atomic message writes remain below the
        # legacy Windows MAX_PATH limit in deeply nested test/user directories.
        staging = self._colonies / f".tmp-{colony.id.hex[:8]}"
        staging.mkdir(parents=True, exist_ok=False)
        try:
            (staging / "sessions").mkdir()
            (staging / "workers").mkdir()
            (staging / "tracker").mkdir()
            (staging / "artifacts").mkdir()
            self._write_model(staging / "metadata.json", colony)

            target_base = staging / "sessions" / str(target.id)
            (target_base / "conversations" / "parts").mkdir(parents=True)
            (target_base / "conversations" / "partials").mkdir()
            (target_base / "data").mkdir()
            self._write_model(target_base / "meta.json", target)

            source_parts = source_base / "conversations" / "parts"
            for source_path in sorted(source_parts.glob("*.json")):
                message = MessageRead.model_validate(read_json(source_path)).model_copy(
                    update={"session_id": target.id}
                )
                self._write_model(
                    target_base / "conversations" / "parts" / source_path.name,
                    message,
                )
            source_spillover = source_base / "spillover"
            if source_spillover.is_dir():
                shutil.copytree(source_spillover, target_base / "spillover")
            final_dir.parent.mkdir(parents=True, exist_ok=True)
            staging.replace(final_dir)
        except BaseException:
            if staging.exists():
                shutil.rmtree(staging)
            raise

    def _write_session_sync(self, session: SessionRead) -> None:
        base = self._session_base(session)
        (base / "conversations" / "parts").mkdir(parents=True, exist_ok=True)
        (base / "conversations" / "partials").mkdir(parents=True, exist_ok=True)
        (base / "data").mkdir(parents=True, exist_ok=True)
        self._write_model(base / "meta.json", session)

    def _append_message_sync(
        self,
        base: Path,
        session: SessionRead,
        message: LLMMessage,
        message_id: UUID | None,
        metadata: Mapping[str, object] | None,
    ) -> MessageRead | None:
        if self._read_session_at_sync(base) is None:
            return None
        parts = base / "conversations" / "parts"
        sequences = [int(path.stem) for path in parts.glob("*.json")]
        sequence = max(sequences, default=0) + 1
        calls = JSON_OBJECTS.validate_python(
            [sanitize_json(call.model_dump(mode="json")) for call in message.tool_calls]
        )
        saved = MessageRead(
            id=message_id or uuid4(),
            session_id=session.id,
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

    def _list_messages_at_sync(self, base: Path) -> list[MessageRead]:
        return [
            MessageRead.model_validate(read_json(path))
            for path in sorted((base / "conversations" / "parts").glob("*.json"))
        ]

    def _get_compaction_checkpoint_at_sync(self, base: Path) -> CompactionCheckpoint | None:
        path = base / "context" / "compaction.json"
        return CompactionCheckpoint.model_validate(read_json(path)) if path.is_file() else None

    def _write_tool_spillover_sync(
        self,
        base: Path,
        tool_name: str,
        value: JsonValue,
    ) -> str:
        directory = base / "spillover"
        directory.mkdir(parents=True, exist_ok=True)
        safe_name = (
            "".join(
                character if character.isalnum() or character in {"-", "_"} else "_"
                for character in tool_name
            )[:60]
            or "tool"
        )
        sequence = len(list(directory.glob("*.json"))) + 1
        filename = f"{sequence:08d}-{safe_name}.json"
        atomic_write_json(
            directory / filename,
            {"value": redact_json(value)},
        )
        return filename

    def _read_tool_spillover_sync(
        self,
        base: Path,
        filename: str,
        offset: int,
        limit: int,
    ) -> dict[str, JsonValue]:
        if Path(filename).name != filename or not filename.endswith(".json"):
            raise ValueError("非法工具结果文件名")
        path = base / "spillover" / filename
        if not path.is_file():
            raise FileNotFoundError(filename)
        serialized = json.dumps(
            read_json(path).get("value"), ensure_ascii=False, separators=(",", ":")
        )
        end = min(len(serialized), offset + limit)
        return {
            "content": serialized[offset:end],
            "offset": offset,
            "next_offset": end if end < len(serialized) else None,
            "total_chars": len(serialized),
            "truncated": end < len(serialized),
        }

    def _create_workers_sync(
        self,
        colony_id: UUID,
        queen_session_id: UUID,
        tasks: Sequence[WorkerTask],
        timeout_seconds: int,
    ) -> list[WorkerRead]:
        now = utc_now()
        parent = self._read_session_sync(colony_id, queen_session_id)
        if parent is None:
            raise RuntimeError(f"Queen session {queen_session_id} does not exist")
        workers: list[WorkerRead] = []
        for task in tasks:
            session_id = uuid4()
            worker_id = uuid4()
            session = SessionRead(
                id=session_id,
                colony_id=colony_id,
                queen_id=parent.queen_id,
                parent_session_id=queen_session_id,
                actor_type="worker",
                status=SessionStatus.QUEUED,
                park_reason=None,
                task={"description": task.task, "data": task.data},
                cursor={"iteration": 0, "phase": "queued"},
                budget={
                    "max_turns": 8,
                    "max_tool_calls": 30,
                    "grace_turns": 2,
                    **{
                        key: value
                        for key, value in parent.budget.items()
                        if key
                        in {
                            "max_context_tokens",
                            "compaction_buffer_tokens",
                            "compaction_buffer_ratio",
                            "compaction_summary_max_tokens",
                            "max_tool_result_chars",
                            "max_verbatim_user_messages",
                        }
                    },
                },
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
        cursor = dict(session.cursor)
        if cursor.get("phase") in {"queued", "idle"}:
            cursor["phase"] = "running"
        self._write_session_sync(
            session.model_copy(
                update={
                    "status": SessionStatus.RUNNING,
                    "cursor": cursor,
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

    def _finish_worker_if_active_sync(
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
        if worker.status not in {
            WorkerStatus.QUEUED,
            WorkerStatus.RUNNING,
            WorkerStatus.REPORTING,
        }:
            return None
        return self._finish_worker_sync(colony_id, worker_id, status, report, error)

    def _attach_worker_report_if_missing_sync(
        self,
        colony_id: UUID,
        worker_id: UUID,
        report: Mapping[str, object],
    ) -> WorkerRead | None:
        path = self._worker_meta_path(colony_id, worker_id)
        if not path.is_file():
            return None
        worker = WorkerRead.model_validate(read_json(path))
        if worker.report is not None or worker.status in {
            WorkerStatus.QUEUED,
            WorkerStatus.RUNNING,
            WorkerStatus.REPORTING,
        }:
            return None
        updated = worker.model_copy(update={"report": JSON_OBJECT.validate_python(dict(report))})
        self._write_model(path, updated)
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
        return self._append_event_at_sync(
            self._events_path(colony_id),
            colony_id,
            event_type,
            session_id,
            worker_run_id,
            payload,
        )

    @staticmethod
    def _append_event_at_sync(
        path: Path,
        colony_id: UUID | None,
        event_type: str,
        session_id: UUID | None,
        worker_run_id: UUID | None,
        payload: Mapping[str, object] | None,
    ) -> ColonyEventRead:
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

    def _session_base(self, session: SessionRead) -> Path:
        if session.colony_id is not None:
            return self._session_dir(session.colony_id, session.id)
        return self.root / "queens" / session.queen_id / "sessions" / str(session.id)

    def _session_dir(self, colony_id: UUID, session_id: UUID) -> Path:
        return self._sessions_dir(colony_id) / str(session_id)

    def _session_meta_path(self, colony_id: UUID, session_id: UUID) -> Path:
        return self._session_dir(colony_id, session_id) / "meta.json"

    def _parts_dir(self, colony_id: UUID, session_id: UUID) -> Path:
        return self._session_dir(colony_id, session_id) / "conversations" / "parts"

    def _compaction_path(self, colony_id: UUID, session_id: UUID) -> Path:
        return self._session_dir(colony_id, session_id) / "context" / "compaction.json"

    def _spillover_dir(self, colony_id: UUID, session_id: UUID) -> Path:
        return self._session_dir(colony_id, session_id) / "spillover"

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
