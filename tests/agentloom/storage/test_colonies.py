"""Tests for file-backed Colony aggregate storage."""

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from agentloom.colony.schemas import (
    ColonyForkCreate,
    ColonySuggestion,
    QueenCreate,
    TaskItemCreate,
    TrackerUpsert,
    WorkerTask,
)
from agentloom.context.schemas import CompactionCheckpoint
from agentloom.llm.base import LLMMessage
from agentloom.runtime.states import SessionStatus, TaskItemStatus, WorkerStatus
from agentloom.storage import LocalColonyStore
from agentloom.user_settings import UserSettingsUpdate


async def create_store(tmp_path: Path) -> LocalColonyStore:
    store = LocalColonyStore(tmp_path)
    await store.initialize()
    await store.update_user_settings(
        UserSettingsUpdate(
            model="mock/schema",
            base_url="http://localhost:8001",
            api_key="test-key",
        )
    )
    await store.create_queen(
        QueenCreate(name="General")
    )
    return store


async def test_colony_state_uses_files_and_one_tracker_database(tmp_path: Path) -> None:
    store = await create_store(tmp_path)
    colony, queen = await store.create("Research", "", "queen_general", {})

    colony_dir = tmp_path / "colonies" / str(colony.id)
    assert (colony_dir / "metadata.json").is_file()
    assert (tmp_path / "queens" / "queen_general" / "profile.yaml").is_file()
    assert (tmp_path / "queens" / "queen_general" / "sessions" / f"{queen.id}.json").is_file()
    assert (colony_dir / "sessions" / str(queen.id) / "meta.json").is_file()
    assert (colony_dir / "tracker" / "tracker.db").is_file()
    assert (colony_dir / "artifacts").is_dir()
    assert await store.get_queen_session(colony.id) == queen
    assert queen.queen_id == "queen_general"
    assert await store.list_queen_sessions("queen_general") == [queen]
    assert await store.list_colonies() == [colony]

    message_id = uuid4()
    message = await store.append_message(
        queen.id,
        LLMMessage(role="user", content="开始"),
        message_id=message_id,
    )
    assert message is not None and message.id == message_id and message.sequence == 1
    assert await store.list_messages(queen.id) == [message]

    event = await store.append_event(
        colony.id,
        "message.created",
        session_id=queen.id,
        payload={"message_id": str(message_id)},
    )
    assert event is not None and event.sequence == 1
    assert await store.list_events_after(colony.id, 0) == [event]

    tracker = await store.upsert_tracker(
        colony.id,
        queen.id,
        TrackerUpsert(namespace="research", entry_key="A", data={"done": False}),
    )
    assert await store.list_tracker(colony.id) == [tracker]


async def test_dm_session_is_stored_under_queen_without_colony(tmp_path: Path) -> None:
    store = await create_store(tmp_path)

    session = await store.create_dm_session("queen_general")

    assert session.colony_id is None
    assert session.session_kind == "dm"
    assert session.operating_phase == "independent"
    assert (
        tmp_path / "queens" / "queen_general" / "sessions" / str(session.id) / "meta.json"
    ).is_file()
    assert await store.list_colonies() == []
    assert list((tmp_path / "colonies").iterdir()) == []
    assert await store.list_queen_sessions("queen_general") == [session]


async def test_idle_dm_session_can_be_moved_to_trash(tmp_path: Path) -> None:
    store = await create_store(tmp_path)
    session = await store.create_dm_session("queen_general")
    source = tmp_path / "queens" / "queen_general" / "sessions" / str(session.id)

    assert await store.delete_session(session.id) is True
    assert not source.exists()
    assert await store.get_session(session.id) is None
    assert len(list((tmp_path / "trash").glob(f"session-{session.id}-*"))) == 1


async def test_running_or_colony_session_cannot_be_deleted_as_dm(tmp_path: Path) -> None:
    store = await create_store(tmp_path)
    dm = await store.create_dm_session("queen_general")
    await store.set_session_status(dm.id, SessionStatus.RUNNING)
    with pytest.raises(ValueError, match="仍在运行"):
        await store.delete_session(dm.id)

    _, queen = await store.create("Research", "", "queen_general", {})
    with pytest.raises(ValueError, match="Colony"):
        await store.delete_session(queen.id)


async def test_dm_fork_preserves_transcript_and_locks_source(tmp_path: Path) -> None:
    store = await create_store(tmp_path)
    source = await store.create_dm_session("queen_general")
    await store.append_message(source.id, LLMMessage(role="user", content="调研两个城市"))
    await store.append_message(source.id, LLMMessage(role="assistant", content="建议并行调研"))
    suggestion = ColonySuggestion(
        id=uuid4(),
        suggested_name="城市调研",
        reason="子任务可并行",
        goal="对比两个城市",
        handoff="保留已确认的偏好",
        proposed_tasks=["调研 A", "调研 B"],
        created_at=datetime.now(UTC),
    )
    await store.set_colony_suggestion(source.id, suggestion)

    colony, target = await store.fork_dm_session(
        source.id,
        ColonyForkCreate(
            suggestion_id=suggestion.id,
            name=suggestion.suggested_name,
            description=suggestion.goal,
        ),
    )

    locked = await store.get_session(source.id)
    copied = await store.list_messages(target.id)
    original = await store.list_messages(source.id)
    assert locked is not None and locked.status is SessionStatus.FORKED
    assert locked.forked_to_colony_id == colony.id
    assert locked.forked_to_session_id == target.id
    assert locked.pending_colony_suggestion is not None
    assert locked.pending_colony_suggestion.status == "accepted"
    assert target.colony_id == colony.id
    assert target.session_kind == "colony"
    assert target.operating_phase == "colony"
    assert copied is not None and original is not None
    assert [item.content for item in copied] == [item.content for item in original]
    assert all(item.session_id == target.id for item in copied)
    assert (tmp_path / "colonies" / str(colony.id) / "tracker" / "tracker.db").is_file()


async def test_reasoning_content_is_persisted_but_not_publicly_serialized(
    tmp_path: Path,
) -> None:
    store = await create_store(tmp_path)
    colony, queen = await store.create("Reasoning", "", "queen_general", {})
    reasoning = "  internal reasoning  "

    message = await store.append_message(
        queen.id,
        LLMMessage(role="assistant", content="完成", reasoning_content=reasoning),
    )

    assert message is not None and message.reasoning_content == reasoning
    message_path = (
        tmp_path
        / "colonies"
        / str(colony.id)
        / "sessions"
        / str(queen.id)
        / "conversations"
        / "parts"
        / "0000000001.json"
    )
    stored = json.loads(message_path.read_text(encoding="utf-8"))
    assert stored["reasoning_content"] == reasoning
    loaded = await store.list_messages(queen.id)
    assert loaded is not None and loaded[0].reasoning_content == reasoning
    assert "reasoning_content" not in loaded[0].model_dump(mode="json")


async def test_compaction_checkpoint_and_spillover_preserve_original_messages(
    tmp_path: Path,
) -> None:
    store = await create_store(tmp_path)
    _, queen = await store.create("Context", "", "queen_general", {})
    original = await store.append_message(queen.id, LLMMessage(role="user", content="原始消息"))
    assert original is not None
    checkpoint = CompactionCheckpoint(
        summary="已压缩摘要",
        through_sequence=original.sequence,
        preserved_sequences=[original.sequence],
        tokens_before=10_000,
        tokens_after=1_000,
        compacted_at=datetime.now(UTC),
    )

    await store.save_compaction_checkpoint(queen.id, checkpoint)
    filename = await store.write_tool_spillover(
        queen.id,
        "search",
        {"token": "secret-value", "content": "abcdefghij"},
    )
    page = await store.read_tool_spillover(queen.id, filename, 0, 8)

    assert await store.get_compaction_checkpoint(queen.id) == checkpoint
    assert await store.list_messages(queen.id) == [original]
    assert page["truncated"] is True
    spill_path = (
        tmp_path
        / "colonies"
        / str(queen.colony_id)
        / "sessions"
        / str(queen.id)
        / "spillover"
        / filename
    )
    assert "secret-value" not in spill_path.read_text(encoding="utf-8")


async def test_workers_tasks_status_and_delete_are_persisted(tmp_path: Path) -> None:
    store = await create_store(tmp_path)
    colony, queen = await store.create("Work", "", "queen_general", {})

    workers = await store.create_workers(
        queen.id,
        [WorkerTask(task="Research A", data={"topic": "A"})],
        30,
    )
    running = await store.mark_worker_running(workers[0].id)
    assert running is not None and running.status is WorkerStatus.RUNNING
    finished = await store.finish_worker(
        running.worker_session_id,
        WorkerStatus.COMPLETED,
        report={"summary": "done"},
    )
    assert finished is not None and finished.report == {"summary": "done"}
    worker_session = await store.get_session(running.worker_session_id)
    assert worker_session is not None and worker_session.status is SessionStatus.COMPLETED
    assert worker_session.budget["max_tool_calls"] == 30
    assert worker_session.budget["grace_turns"] == 2
    assert queen.budget["grace_turns"] == 1

    task = await store.create_task_item(
        colony.id,
        queen.id,
        TaskItemCreate(title="Summarize"),
    )
    updated = await store.update_task_status(task.id, TaskItemStatus.COMPLETED)
    assert updated is not None and updated.status is TaskItemStatus.COMPLETED
    assert await store.list_tasks(colony.id) == [updated]

    assert await store.rename_colony(colony.id, "Renamed")
    renamed = await store.get(colony.id)
    assert renamed is not None and renamed.name == "Renamed"
    assert await store.delete_colony(colony.id)
    assert await store.get(colony.id) is None
    assert await store.get_session(queen.id) is None
    assert not (tmp_path / "queens" / "general" / "sessions" / f"{queen.id}.json").exists()
    assert any((tmp_path / "trash").iterdir())


async def test_recovery_requeues_running_workers_and_queens(tmp_path: Path) -> None:
    store = await create_store(tmp_path)
    colony, queen = await store.create("Recovery", "", "queen_general", {})
    worker = (await store.create_workers(queen.id, [WorkerTask(task="A")], 30))[0]
    await store.mark_worker_running(worker.id)
    worker_cursor = {
        "iteration": 3,
        "phase": "budget_grace",
        "budget_reason": "tool_calls",
        "budget_tool_calls": 30,
        "grace_turn": 1,
    }
    await store.set_session_status(
        worker.worker_session_id,
        SessionStatus.RUNNING,
        cursor=worker_cursor,
    )
    await store.set_session_status(queen.id, SessionStatus.RUNNING)

    worker_ids, queen_ids = await store.recover_interrupted()

    assert worker_ids == [worker.id]
    assert queen_ids == [queen.id]
    recovered_worker = (await store.list_workers(colony.id))[0]
    recovered_queen = await store.get_session(queen.id)
    assert recovered_worker.status is WorkerStatus.QUEUED
    assert recovered_queen is not None and recovered_queen.status is SessionStatus.QUEUED

    await store.mark_worker_running(worker.id)
    resumed_session = await store.get_session(worker.worker_session_id)
    assert resumed_session is not None
    assert resumed_session.cursor == worker_cursor
