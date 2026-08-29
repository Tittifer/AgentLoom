"""In-process wake-up coordination for persisted Colony events."""

import asyncio
from uuid import UUID


class ColonyEventNotifier:
    """Wake local streams while keeping PostgreSQL as the event source of truth."""

    def __init__(self) -> None:
        self._condition = asyncio.Condition()
        self._versions: dict[UUID, int] = {}

    def version(self, colony_id: UUID) -> int:
        return self._versions.get(colony_id, 0)

    async def notify(self, colony_id: UUID) -> None:
        async with self._condition:
            self._versions[colony_id] = self.version(colony_id) + 1
            self._condition.notify_all()

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


__all__ = ["ColonyEventNotifier"]
