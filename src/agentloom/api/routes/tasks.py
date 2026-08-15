"""Task HTTP endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from agentloom.api.schemas import ApiError, PaginatedResponse, TaskCreate, TaskRead
from agentloom.db.session import get_db_session
from agentloom.repositories.tasks import TaskRepository
from agentloom.runtime.states import TaskStatus
from agentloom.services.task_service import TaskNotFoundError, TaskService

router = APIRouter(prefix="/tasks", tags=["tasks"])

DatabaseSession = Annotated[AsyncSession, Depends(get_db_session)]
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]


def get_task_service(session: DatabaseSession) -> TaskService:
    """Build a task service for the current request transaction."""

    return TaskService(TaskRepository(session))


TaskServiceDependency = Annotated[TaskService, Depends(get_task_service)]


@router.post("", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
async def create_task(
    task: TaskCreate,
    service: TaskServiceDependency,
) -> TaskRead:
    """Create and return a draft task."""

    return await service.create_task(task)


@router.get("", response_model=PaginatedResponse[TaskRead])
async def list_tasks(
    service: TaskServiceDependency,
    page: Page = 1,
    page_size: PageSize = 20,
    task_status: Annotated[TaskStatus | None, Query(alias="status")] = None,
) -> PaginatedResponse[TaskRead]:
    """List tasks with pagination and optional status filtering."""

    return await service.list_tasks(page, page_size, task_status)


@router.get(
    "/{task_id}",
    response_model=TaskRead,
    responses={status.HTTP_404_NOT_FOUND: {"model": ApiError}},
)
async def get_task(
    task_id: UUID,
    service: TaskServiceDependency,
) -> TaskRead | JSONResponse:
    """Return one task or the standard missing-task response."""

    try:
        return await service.get_task(task_id)
    except TaskNotFoundError:
        error = ApiError(
            code="TASK_NOT_FOUND",
            message="Task not found",
        )
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content=error.model_dump(mode="json"),
        )


__all__ = ["router"]
