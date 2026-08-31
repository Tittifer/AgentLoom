"""In-process delivery for persisted-event wakeups and transient stream deltas."""

import asyncio
from collections.abc import AsyncGenerator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import UUID

from pydantic import JsonValue


@dataclass(frozen=True)
class TransientColonyEvent:
    """An in-memory SSE event that must not create one database row per token."""

    type: str
    payload: Mapping[str, JsonValue]


class ColonyEventNotifier:
    """Wake local streams while keeping PostgreSQL as the event source of truth."""

    def __init__(self) -> None:
        self._condition = asyncio.Condition()
        self._versions: dict[UUID, int] = {}
        self._subscribers: dict[
            UUID,
            set[asyncio.Queue[TransientColonyEvent | None]],
        ] = {}

    def version(self, colony_id: UUID) -> int:
        return self._versions.get(colony_id, 0)

    async def notify(self, colony_id: UUID) -> None:
        async with self._condition:
            self._versions[colony_id] = self.version(colony_id) + 1
            self._condition.notify_all()
        for queue in tuple(self._subscribers.get(colony_id, ())):
            queue.put_nowait(None)

    async def publish(
        self,
        colony_id: UUID,
        event_type: str,
        payload: Mapping[str, JsonValue],
    ) -> None:
        """Fan out a non-persistent event to currently connected clients."""

        event = TransientColonyEvent(type=event_type, payload=payload)
        for queue in tuple(self._subscribers.get(colony_id, ())):
            queue.put_nowait(event)

    @asynccontextmanager
    async def subscribe(
        self,
        colony_id: UUID,
    ) -> AsyncGenerator[asyncio.Queue[TransientColonyEvent | None], None]:
        queue: asyncio.Queue[TransientColonyEvent | None] = asyncio.Queue()
        subscribers = self._subscribers.setdefault(colony_id, set())
        subscribers.add(queue)
        try:
            yield queue
        finally:
            subscribers.discard(queue)
            if not subscribers:
                self._subscribers.pop(colony_id, None)

    async def wait_for_change(self, colony_id: UUID, observed_version: int, timeout: float) -> bool:
        async with self._condition:
            try:
                await asyncio.wait_for(
                    self._condition.wait_for(lambda: self.version(colony_id) != observed_version),
                    timeout=timeout,
                )
            except TimeoutError:
                return False
        return True


__all__ = ["ColonyEventNotifier", "TransientColonyEvent"]
