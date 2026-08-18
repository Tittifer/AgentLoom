"""Run creation and query application service."""

from uuid import UUID

from agentloom.db.base import JsonObject
from agentloom.repositories.runs import RunRepository
from agentloom.repositories.tasks import TaskRepository
from agentloom.repositories.workflows import WorkflowRepository
from agentloom.runtime.run import AgentMessageRead, RunRead, RunSnapshot
from agentloom.runtime.states import TaskStatus
from agentloom.services.task_service import TaskNotFoundError


class TaskNotReadyError(ValueError):
    """Raised when a run is requested for a task that is not ready."""


class WorkflowNotFoundError(LookupError):
    """Raised when a ready task has no persisted workflow."""


class RunNotFoundError(LookupError):
    """Raised when a requested run does not exist."""


class NodeRunNotFoundError(LookupError):
    """Raised when a requested node attempt does not exist."""


class RunService:
    """Coordinate run use cases across task, workflow, and run repositories."""

    def __init__(
        self,
        task_repository: TaskRepository,
        workflow_repository: WorkflowRepository,
        run_repository: RunRepository,
    ) -> None:
        self._tasks = task_repository
        self._workflows = workflow_repository
        self._runs = run_repository

    async def start_run(self, task_id: UUID) -> RunRead:
        """Create a queued run for the latest workflow of a ready task."""

        task = await self._tasks.get(task_id)
        if task is None:
            raise TaskNotFoundError(task_id)
        if task.status is not TaskStatus.READY:
            raise TaskNotReadyError

        workflow = await self._workflows.get_latest_for_task(task_id)
        if workflow is None:
            raise WorkflowNotFoundError

        claimed_task = await self._tasks.update_status(
            task.id,
            TaskStatus.READY,
            TaskStatus.RUNNING,
        )
        if claimed_task is None:
            raise TaskNotReadyError

        run_input: JsonObject = {
            "goal": task.goal,
            "context": task.context,
        }
        return await self._runs.create(task.id, workflow, run_input)

    async def get_run(self, run_id: UUID) -> RunSnapshot:
        """Return the complete run snapshot used by the detail API."""

        snapshot = await self._runs.get_snapshot(run_id)
        if snapshot is None:
            raise RunNotFoundError
        return snapshot

    async def get_node_messages(self, node_run_id: UUID) -> list[AgentMessageRead]:
        """Return all visible messages for one node attempt."""

        messages = await self._runs.get_node_messages(node_run_id)
        if messages is None:
            raise NodeRunNotFoundError
        return messages


__all__ = [
    "NodeRunNotFoundError",
    "RunNotFoundError",
    "RunService",
    "TaskNotReadyError",
    "WorkflowNotFoundError",
]
