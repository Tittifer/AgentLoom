"""Tests for isolated live Session resources."""

import asyncio
from uuid import UUID, uuid4

from agentloom.llm.mock import SchemaMockLLMProvider
from agentloom.sessions import SessionManager


class StubLoop:
    def __init__(self, active: set[str] | None = None, overlap: list[bool] | None = None) -> None:
        self.active = active
        self.overlap = overlap

    async def run(self, session_id: UUID) -> None:
        if self.active is None or self.overlap is None:
            return
        key = str(session_id)
        self.overlap.append(key in self.active)
        self.active.add(key)
        await asyncio.sleep(0)
        self.active.remove(key)


def test_manager_reuses_resources_only_within_the_same_session() -> None:
    manager = SessionManager[StubLoop]()
    provider = SchemaMockLLMProvider()
    first_id = uuid4()
    second_id = uuid4()
    created: list[StubLoop] = []

    def factory(_: object) -> StubLoop:
        loop = StubLoop()
        created.append(loop)
        return loop

    first = manager.get_or_create(first_id, provider, factory)
    assert manager.get_or_create(first_id, provider, factory) is first
    assert manager.get_or_create(second_id, provider, factory) is not first
    assert len(created) == 2


async def test_manager_serializes_one_execution_without_blocking_another() -> None:
    manager = SessionManager[StubLoop]()
    active: set[str] = set()
    overlap: list[bool] = []
    loop = StubLoop(active, overlap)
    first_id = uuid4()
    second_id = uuid4()

    await asyncio.gather(
        manager.run(first_id, loop),
        manager.run(first_id, loop),
        manager.run(second_id, loop),
    )

    assert overlap == [False, False, False]


async def test_clearing_live_resources_preserves_an_active_execution_lock() -> None:
    manager = SessionManager[StubLoop]()
    provider = SchemaMockLLMProvider()
    session_id = uuid4()
    live = manager.get_or_create(session_id, provider, lambda _: StubLoop())
    await live.run_lock.acquire()
    try:
        manager.clear()
        replacement = manager.get_or_create(session_id, provider, lambda _: StubLoop())
        assert replacement is not live
        assert replacement.run_lock is live.run_lock
    finally:
        live.run_lock.release()


async def test_task_cancellation_is_scoped_to_its_owner_session() -> None:
    manager = SessionManager[StubLoop]()
    release = asyncio.Event()

    async def wait_for_release() -> None:
        await release.wait()

    first_id = uuid4()
    second_id = uuid4()
    first = asyncio.create_task(wait_for_release())
    second = asyncio.create_task(wait_for_release())
    manager.track_task(first_id, first)
    manager.track_task(second_id, second)

    await manager.cancel_tasks(first_id)

    assert first.cancelled()
    assert not second.done()
    release.set()
    await second
