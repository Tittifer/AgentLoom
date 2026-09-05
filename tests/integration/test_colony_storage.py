"""Integration tests for persistent Colony storage."""

import asyncio
from pathlib import Path

from agentloom.colony.schemas import QueenCreate, TaskItemCreate, TrackerUpsert, WorkerTask
from agentloom.storage import LocalColonyStore


async def create_store(tmp_path: Path) -> LocalColonyStore:
    store = LocalColonyStore(tmp_path)
    await store.initialize()
    await store.create_queen(
        QueenCreate(
            name="General",
            model="mock/schema",
            base_url="http://localhost:8001",
            api_key="test-key",
        )
    )
    return store


async def test_concurrent_colony_writes_have_unique_events(tmp_path: Path) -> None:
    store = await create_store(tmp_path)
    colony, queen = await store.create("Concurrent", "", "queen_general", {})

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
    first = await create_store(tmp_path)
    colony, queen = await first.create("Persistent", "", "queen_general", {})
    await first.create_task_item(colony.id, queen.id, TaskItemCreate(title="Survives"))

    reopened = LocalColonyStore(tmp_path)
    await reopened.initialize()

    assert await reopened.get(colony.id) == colony
    assert [task.title for task in await reopened.list_tasks(colony.id)] == ["Survives"]
