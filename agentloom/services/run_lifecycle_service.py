"""Committed cancellation and retry commands for workflow runs."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentloom.repositories.events import RunEventRepository
from agentloom.repositories.runs import RunRepository
from agentloom.repositories.tasks import TaskRepository
from agentloom.runtime.run import RunRead
from agentloom.runtime.states import RunStatus, TaskStatus
from agentloom.services.event_service import EventService, RunEventNotifier
from agentloom.services.run_service import RunNotFoundError


class RunNotCancellableError(ValueError):
    """Raised when cancellation targets a terminal run."""


class RunNotRetryableError(ValueError):
    """Raised when retry targets a non-failed or superseded run."""


class RunLifecycleService:
    """Apply run commands with commit-before-notify transaction boundaries."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        notifier: RunEventNotifier,
    ) -> None:
        self._session_factory = session_factory
        self._notifier = notifier

    async def cancel_run(self, run_id: UUID) -> RunRead:
        """Cancel an active run and notify SSE listeners after commit."""

        async with self._session_factory.begin() as session:
            repository = RunRepository(session)
            snapshot = await repository.get_snapshot(run_id)
            if snapshot is None:
                raise RunNotFoundError
            if snapshot.run.status not in {RunStatus.QUEUED, RunStatus.RUNNING}:
                raise RunNotCancellableError

            cancelled = await repository.cancel_run(run_id)
            if cancelled is None:
                raise RunNotCancellableError
            await EventService(RunEventRepository(session)).append(
                run_id,
                "run.cancelled",
                payload={"status": "cancelled"},
            )

        await self._notifier.notify(run_id)
        return cancelled

    async def retry_run(self, run_id: UUID) -> RunRead:
        """Create a new queued run from one failed run without mutating history."""

        async with self._session_factory.begin() as session:
            repository = RunRepository(session)
            snapshot = await repository.get_snapshot(run_id)
            if snapshot is None:
                raise RunNotFoundError
            if snapshot.run.status is not RunStatus.FAILED:
                raise RunNotRetryableError

            claimed_task = await TaskRepository(session).update_status(
                snapshot.run.task_id,
                TaskStatus.FAILED,
                TaskStatus.RUNNING,
            )
            if claimed_task is None:
                raise RunNotRetryableError
            return await repository.create(
                snapshot.run.task_id,
                snapshot.workflow,
                snapshot.run.input,
            )


__all__ = ["RunLifecycleService", "RunNotCancellableError", "RunNotRetryableError"]
