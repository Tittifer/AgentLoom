"""DAG readiness calculation and in-process run scheduling."""

import asyncio
from typing import Protocol
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentloom.db.base import JsonObject
from agentloom.repositories.events import RunEventRepository
from agentloom.repositories.runs import RunRepository
from agentloom.runtime.run import NodeRunRead, RunSnapshot
from agentloom.runtime.states import NodeRunStatus, RunStatus
from agentloom.runtime.workflow import WorkflowNodeRead
from agentloom.services.event_service import EventService, RunEventNotifier


class NodeExecutor(Protocol):
    """Node execution behavior consumed by the scheduler."""

    async def execute(self, run_id: UUID, node_key: str) -> None: ...


def find_ready_nodes(snapshot: RunSnapshot) -> list[WorkflowNodeRead]:
    """Return runnable nodes up to the run's remaining concurrency capacity."""

    if snapshot.run.status not in {RunStatus.QUEUED, RunStatus.RUNNING}:
        return []

    remaining_capacity = snapshot.max_parallel_nodes - snapshot.current_running_nodes
    if remaining_capacity <= 0:
        return []

    node_runs = {node_run.node_key: node_run for node_run in snapshot.node_runs}
    ready: list[WorkflowNodeRead] = []
    for node in snapshot.workflow.nodes:
        node_run = node_runs[node.key]
        if node_run.status not in {NodeRunStatus.PENDING, NodeRunStatus.RETRYING}:
            continue
        if all(
            node_runs[dependency].status is NodeRunStatus.COMPLETED
            for dependency in node.depends_on
        ):
            ready.append(node)
        if len(ready) == remaining_capacity:
            break
    return ready


class RunScheduler:
    """Poll and advance queued or running DAG executions in one backend process."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        executor: NodeExecutor,
        event_notifier: RunEventNotifier,
        poll_interval: float = 0.5,
        max_global_concurrency: int = 10,
    ) -> None:
        self._session_factory = session_factory
        self._executor = executor
        self._event_notifier = event_notifier
        self._poll_interval = poll_interval
        self._semaphore = asyncio.Semaphore(max_global_concurrency)
        self._stop_event = asyncio.Event()
        self._loop_task: asyncio.Task[None] | None = None
        self._run_tasks: dict[UUID, asyncio.Task[None]] = {}
        self._active_run_ids: set[UUID] = set()
        self._logger = structlog.get_logger(__name__)

    async def start(self) -> None:
        """Start polling for runnable runs once."""

        if self._loop_task is not None:
            return
        self._stop_event.clear()
        self._loop_task = asyncio.create_task(self._poll_loop())

    async def stop(self) -> None:
        """Stop polling and wait for already claimed runs to finish."""

        if self._loop_task is None:
            return
        self._stop_event.set()
        await self._loop_task
        self._loop_task = None
        if self._run_tasks:
            await asyncio.gather(*tuple(self._run_tasks.values()), return_exceptions=True)

    async def scan_once(self) -> None:
        """Claim one batch and start each run at most once in this process."""

        async with self._session_factory.begin() as session:
            run_ids = await RunRepository(session).claim_runnable_run_ids()
            new_run_ids = [run_id for run_id in run_ids if run_id not in self._active_run_ids]
            self._active_run_ids.update(new_run_ids)

        for run_id in new_run_ids:
            self._run_tasks[run_id] = asyncio.create_task(self._advance_active_run(run_id))

    async def _poll_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self.scan_once()
            except Exception:
                self._logger.exception("run_scheduler_scan_failed")

            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self._poll_interval,
                )
            except TimeoutError:
                continue

    async def _advance_active_run(self, run_id: UUID) -> None:
        try:
            await self._advance_run(run_id)
        except Exception:
            self._logger.exception("run_scheduler_advance_failed", run_id=str(run_id))
        finally:
            self._active_run_ids.discard(run_id)
            self._run_tasks.pop(run_id, None)

    async def _advance_run(self, run_id: UUID) -> None:
        while True:
            run_started = False
            async with self._session_factory.begin() as session:
                repository = RunRepository(session)
                snapshot = await repository.get_snapshot(run_id)
                if snapshot is None or snapshot.is_terminal:
                    return
                if snapshot.run.status is RunStatus.QUEUED:
                    run_started = await repository.mark_run_running(run_id)
                    if run_started:
                        await EventService(RunEventRepository(session)).append(
                            run_id,
                            "run.started",
                            payload={"status": "running"},
                        )

            if snapshot.run.status is RunStatus.QUEUED:
                if run_started:
                    await self._event_notifier.notify(run_id)
                continue

            ready_nodes = find_ready_nodes(snapshot)
            if ready_nodes:
                await asyncio.gather(
                    *(self._execute_node(run_id, node.key) for node in ready_nodes),
                    return_exceptions=True,
                )
                continue

            if snapshot.has_running_nodes:
                await asyncio.sleep(self._poll_interval)
                continue

            await self._finish_or_fail(snapshot)
            return

    async def _execute_node(self, run_id: UUID, node_key: str) -> None:
        async with self._semaphore:
            await self._executor.execute(run_id, node_key)

    async def _finish_or_fail(self, snapshot: RunSnapshot) -> None:
        node_runs: dict[str, NodeRunRead] = {
            node_run.node_key: node_run for node_run in snapshot.node_runs
        }
        all_completed = all(
            node_run.status is NodeRunStatus.COMPLETED for node_run in node_runs.values()
        )
        event_written = False
        async with self._session_factory.begin() as session:
            repository = RunRepository(session)
            events = EventService(RunEventRepository(session))
            if all_completed:
                result = node_runs[snapshot.workflow.final_node].output or {}
                event_written = await repository.complete_run(snapshot.run.id, result)
                if event_written:
                    await events.append(
                        snapshot.run.id,
                        "run.completed",
                        payload={"status": "completed"},
                    )
            else:
                failed_nodes = sorted(
                    key
                    for key, node_run in node_runs.items()
                    if node_run.status is NodeRunStatus.FAILED
                )
                error: JsonObject
                if failed_nodes:
                    error = {
                        "code": "NODE_EXECUTION_FAILED",
                        "failed_nodes": failed_nodes,
                    }
                else:
                    error = {
                        "code": "RUN_DEADLOCKED",
                        "message": "No nodes are running or ready",
                    }
                event_written = await repository.fail_run(snapshot.run.id, error)
                if event_written:
                    await events.append(
                        snapshot.run.id,
                        "run.failed",
                        payload={
                            "status": "failed",
                            "code": error["code"],
                        },
                    )
        if event_written:
            await self._event_notifier.notify(snapshot.run.id)


__all__ = ["NodeExecutor", "RunScheduler", "find_ready_nodes"]
