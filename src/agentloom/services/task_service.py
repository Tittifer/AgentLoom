"""Task application service."""

from uuid import UUID

from agentloom.api.schemas import PaginatedResponse, TaskCreate, TaskRead
from agentloom.repositories.tasks import TaskRepository
from agentloom.runtime.states import TaskStatus


class TaskNotFoundError(LookupError):
    """Raised when a requested task does not exist."""

    def __init__(self, task_id: UUID) -> None:
        self.task_id = task_id
        super().__init__(f"Task {task_id} was not found")


class TaskService:
    """Coordinate task use cases without exposing persistence details."""

    def __init__(self, repository: TaskRepository) -> None:
        self._repository = repository

    async def create_task(self, task: TaskCreate) -> TaskRead:
        """Create a new draft task."""

        return await self._repository.create(task)

    async def get_task(self, task_id: UUID) -> TaskRead:
        """Return a task or raise a domain-specific missing-resource error."""

        task = await self._repository.get(task_id)
        if task is None:
            raise TaskNotFoundError(task_id)
        return task

    async def list_tasks(
        self,
        page: int,
        page_size: int,
        status: TaskStatus | None = None,
    ) -> PaginatedResponse[TaskRead]:
        """Return one filtered page of tasks."""

        return await self._repository.list(page, page_size, status)


__all__ = ["TaskNotFoundError", "TaskService"]
