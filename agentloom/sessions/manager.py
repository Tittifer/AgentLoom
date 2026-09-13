"""In-process lifecycle for isolated Queen sessions and agent executions."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from time import monotonic
from typing import Generic, Protocol, TypeVar
from uuid import UUID

from agentloom.llm.base import LLMProvider


class RunnableLoop(Protocol):
    async def run(self, session_id: UUID) -> None: ...


LoopT = TypeVar("LoopT", bound=RunnableLoop)
LoopFactory = Callable[[LLMProvider], LoopT]


@dataclass(slots=True)
class LiveSession(Generic[LoopT]):
    """Resources owned by one live Queen session."""

    id: UUID
    provider: LLMProvider
    queen_loop: LoopT
    event_stream_id: UUID
    loaded_at: float = field(default_factory=monotonic)
    run_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class SessionManager(Generic[LoopT]):
    """Keep live Session resources isolated from every other conversation."""

    def __init__(self) -> None:
        self._sessions: dict[UUID, LiveSession[LoopT]] = {}
        self._execution_locks: dict[UUID, asyncio.Lock] = {}
        self._tasks: dict[UUID, set[asyncio.Task[None]]] = {}

    def get(self, session_id: UUID) -> LiveSession[LoopT] | None:
        return self._sessions.get(session_id)

    def get_or_create(
        self,
        session_id: UUID,
        provider: LLMProvider,
        loop_factory: LoopFactory[LoopT],
    ) -> LiveSession[LoopT]:
        current = self._sessions.get(session_id)
        if current is not None:
            return current
        run_lock = self._execution_locks.setdefault(session_id, asyncio.Lock())
        session = LiveSession(
            id=session_id,
            provider=provider,
            queen_loop=loop_factory(provider),
            event_stream_id=session_id,
            run_lock=run_lock,
        )
        self._sessions[session_id] = session
        return session

    async def run(self, execution_id: UUID, loop: RunnableLoop) -> None:
        lock = self._execution_locks.setdefault(execution_id, asyncio.Lock())
        async with lock:
            await loop.run(execution_id)

    def track_task(self, session_id: UUID, task: asyncio.Task[None]) -> None:
        self._tasks.setdefault(session_id, set()).add(task)
        task.add_done_callback(lambda completed: self._task_done(session_id, completed))

    async def cancel_tasks(self, session_id: UUID) -> None:
        current = asyncio.current_task()
        tasks = tuple(
            task
            for task in self._tasks.get(session_id, ())
            if task is not current and not task.done()
        )
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def _task_done(self, session_id: UUID, task: asyncio.Task[None]) -> None:
        tasks = self._tasks.get(session_id)
        if tasks is None:
            return
        tasks.discard(task)
        if not tasks:
            self._tasks.pop(session_id, None)

    def discard(self, session_id: UUID) -> None:
        self._sessions.pop(session_id, None)
        self._execution_locks.pop(session_id, None)
        self._tasks.pop(session_id, None)

    def clear(self) -> None:
        self._sessions.clear()
        self._execution_locks = {
            execution_id: lock
            for execution_id, lock in self._execution_locks.items()
            if lock.locked()
        }


__all__ = ["LiveSession", "SessionManager"]
