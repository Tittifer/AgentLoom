"""Task HTTP endpoints."""

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from agentloom.agents.planner import Planner, PlannerGenerationError, PlannerProviderError
from agentloom.api.schemas import ApiError, ApiErrorDetail, PaginatedResponse, TaskCreate, TaskRead
from agentloom.db.session import DatabaseSessionManager, get_db_session
from agentloom.repositories.tasks import TaskRepository
from agentloom.runtime.states import TaskStatus
from agentloom.runtime.workflow import WorkflowRead
from agentloom.services.planning_service import PlanningService, TaskNotPlannableError
from agentloom.services.task_service import TaskNotFoundError, TaskService

router = APIRouter(prefix="/tasks", tags=["tasks"])

DatabaseSession = Annotated[AsyncSession, Depends(get_db_session)]
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]


def get_task_service(session: DatabaseSession) -> TaskService:
    """Build a task service for the current request transaction."""

    return TaskService(TaskRepository(session))


TaskServiceDependency = Annotated[TaskService, Depends(get_task_service)]


def get_planning_service(request: Request) -> PlanningService:
    """Build planning around the application-owned database and Planner."""

    database = cast(DatabaseSessionManager, request.app.state.database)
    planner = cast(Planner, request.app.state.planner)
    return PlanningService(database.session_factory, planner)


PlanningServiceDependency = Annotated[PlanningService, Depends(get_planning_service)]


def error_response(
    status_code: int,
    code: str,
    message: str,
    details: list[ApiErrorDetail] | None = None,
) -> JSONResponse:
    """Build a standard task API error response."""

    error = ApiError(code=code, message=message, details=details or [])
    return JSONResponse(
        status_code=status_code,
        content=error.model_dump(mode="json"),
    )


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


@router.post(
    "/{task_id}/plan",
    response_model=WorkflowRead,
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ApiError},
        status.HTTP_409_CONFLICT: {"model": ApiError},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ApiError},
        status.HTTP_502_BAD_GATEWAY: {"model": ApiError},
    },
)
async def plan_task(
    task_id: UUID,
    service: PlanningServiceDependency,
) -> WorkflowRead | JSONResponse:
    """Generate and persist a validated workflow for one draft task."""

    try:
        return await service.plan_task(task_id)
    except TaskNotFoundError:
        return error_response(404, "TASK_NOT_FOUND", "Task not found")
    except TaskNotPlannableError:
        return error_response(409, "TASK_NOT_PLANNABLE", "Task is not in draft state")
    except PlannerGenerationError as error:
        details = [ApiErrorDetail(path=issue.path, reason=issue.reason) for issue in error.issues]
        return error_response(
            422,
            "PLANNING_FAILED",
            "Planner could not generate a valid workflow",
            details,
        )
    except PlannerProviderError:
        return error_response(502, "PLANNER_PROVIDER_ERROR", "Planner model request failed")


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
        return error_response(404, "TASK_NOT_FOUND", "Task not found")


__all__ = ["router"]
