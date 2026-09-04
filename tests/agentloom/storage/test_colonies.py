"""Tests for file-backed Colony aggregate storage."""

from pathlib import Path
from uuid import uuid4

from agentloom.colony.schemas import TaskItemCreate, TrackerUpsert, WorkerTask
from agentloom.llm.base import LLMMessage
from agentloom.runtime.states import SessionStatus, TaskItemStatus, WorkerStatus
from agentloom.storage import LocalColonyStore


async def create_store(tmp_path: Path) -> LocalColonyStore:
    store = LocalColonyStore(tmp_path)
    await store.initialize()
    return store


async def test_colony_state_uses_files_and_one_tracker_database(tmp_path: Path) -> None:
    store = await create_store(tmp_path)
    colony, queen = await store.create("Research", "", "general", "mock/schema", {})

    colony_dir = tmp_path / "colonies" / str(colony.id)
    assert (colony_dir / "metadata.json").is_file()
    assert (colony_dir / "sessions" / str(queen.id) / "meta.json").is_file()
    assert (colony_dir / "tracker" / "tracker.db").is_file()
    assert (colony_dir / "artifacts").is_dir()
    assert await store.get_queen_session(colony.id) == queen
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


async def test_workers_tasks_status_and_delete_are_persisted(tmp_path: Path) -> None:
    store = await create_store(tmp_path)
    colony, queen = await store.create("Work", "", "general", "mock/schema", {})

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
    assert any((tmp_path / "trash").iterdir())


async def test_recovery_requeues_running_workers_and_queens(tmp_path: Path) -> None:
    store = await create_store(tmp_path)
    colony, queen = await store.create("Recovery", "", "general", "mock/schema", {})
    worker = (await store.create_workers(queen.id, [WorkerTask(task="A")], 30))[0]
    await store.mark_worker_running(worker.id)
    await store.set_session_status(queen.id, SessionStatus.RUNNING)

    worker_ids, queen_ids = await store.recover_interrupted()

    assert worker_ids == [worker.id]
    assert queen_ids == [queen.id]
    recovered_worker = (await store.list_workers(colony.id))[0]
    recovered_queen = await store.get_session(queen.id)
    assert recovered_worker.status is WorkerStatus.QUEUED
    assert recovered_queen is not None and recovered_queen.status is SessionStatus.QUEUED
