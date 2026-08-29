"""Run-event creation, replay, and in-process wake-up coordination."""

import asyncio
from collections.abc import Mapping
from uuid import UUID

from agentloom.repositories.events import RunEventRepository
from agentloom.runtime.run import RunEventRead, RunEventType


class EventRunNotFoundError(Exception):
    """Raised when an event targets a missing run."""


class RunEventNotifier:
    """Wake local SSE streams without making notifications the source of truth."""

    def __init__(self) -> None:
        self._condition = asyncio.Condition()
        self._versions: dict[UUID, int] = {}

    def version(self, run_id: UUID) -> int:
        """Capture a run's current notification version before querying storage."""

        return self._versions.get(run_id, 0)

    async def notify(self, run_id: UUID) -> None:
        """Wake every local stream waiting for newly committed run events."""

        async with self._condition:
            self._versions[run_id] = self.version(run_id) + 1
            self._condition.notify_all()

    async def wait_for_change(
        self,
        run_id: UUID,
        observed_version: int,
        timeout: float,
    ) -> bool:
        """Wait until the run changes, returning False when heartbeat time elapses."""

        async with self._condition:
            try:
                await asyncio.wait_for(
                    self._condition.wait_for(lambda: self.version(run_id) != observed_version),
                    timeout=timeout,
                )
            except TimeoutError:
                return False
        return True


class EventService:
    """Append and replay persistent run events."""

    def __init__(self, repository: RunEventRepository) -> None:
        self._repository = repository

    async def append(
        self,
        run_id: UUID,
        event_type: RunEventType,
        *,
        node_key: str | None = None,
        payload: Mapping[str, object] | None = None,
    ) -> RunEventRead:
        """Lock the run and append its next event in the current transaction."""

        if not await self._repository.lock_run(run_id):
            raise EventRunNotFoundError(str(run_id))
        sequence = await self._repository.next_sequence(run_id)
        return await self._repository.create(
            run_id,
            sequence,
            event_type,
            node_key,
            payload or {},
        )

    async def list_after(self, run_id: UUID, sequence: int) -> list[RunEventRead]:
        """Replay events after the supplied sequence."""

        return await self._repository.list_after(run_id, sequence)

    async def run_exists(self, run_id: UUID) -> bool:
        """Return whether a stream can be opened for the run."""

        return await self._repository.run_exists(run_id)


__all__ = ["EventRunNotFoundError", "EventService", "RunEventNotifier"]
