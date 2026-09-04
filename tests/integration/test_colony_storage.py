"""Integration tests for persistent Colony storage."""

import asyncio
from pathlib import Path

from agentloom.colony.schemas import TaskItemCreate, TrackerUpsert, WorkerTask
from agentloom.storage import LocalColonyStore


async def test_concurrent_colony_writes_have_unique_events(tmp_path: Path) -> None:
    store = LocalColonyStore(tmp_path)
    await store.initialize()
    colony, queen = await store.create("Concurrent", "", "general", "mock/schema", {})

    async def update_tracker() -> None:
        await store.upsert_tracker(
            colony.id,
            queen.id,
            TrackerUpsert(namespace="trip", entry_key="cities", data={"count": 2}),
        )
        await store.append_event(colony.id, "tracker.updated", session_id=queen.id)

    async def create_task() -> None:
        await store.create_task_item(
            colony.id,
            queen.id,
            TaskItemCreate(title="Compare cities"),
        )
        await store.append_event(colony.id, "task.created", session_id=queen.id)

    async def create_worker() -> None:
        worker = (await store.create_workers(queen.id, [WorkerTask(task="Research")], 30))[0]
        await store.append_event(
            colony.id,
            "worker.queued",
            session_id=worker.worker_session_id,
            worker_run_id=worker.id,
        )

    await asyncio.gather(update_tracker(), create_task(), create_worker())

    events = await store.list_events_after(colony.id, 0)
    assert events is not None
    assert [event.sequence for event in events] == [1, 2, 3]
    assert len(await store.list_tracker(colony.id)) == 1
    assert len(await store.list_tasks(colony.id)) == 1
    assert len(await store.list_workers(colony.id)) == 1


async def test_new_store_instance_reads_existing_state(tmp_path: Path) -> None:
    first = LocalColonyStore(tmp_path)
    await first.initialize()
    colony, queen = await first.create("Persistent", "", "general", "mock/schema", {})
    await first.create_task_item(colony.id, queen.id, TaskItemCreate(title="Survives"))

    reopened = LocalColonyStore(tmp_path)
    await reopened.initialize()

    assert await reopened.get(colony.id) == colony
    assert [task.title for task in await reopened.list_tasks(colony.id)] == ["Survives"]
