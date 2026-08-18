"""Run and node-attempt HTTP endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from agentloom.api.schemas import ApiError
from agentloom.db.session import get_db_session
from agentloom.repositories.runs import RunRepository
from agentloom.repositories.tasks import TaskRepository
from agentloom.repositories.workflows import WorkflowRepository
from agentloom.runtime.run import AgentMessageRead, RunRead, RunSnapshot
from agentloom.services.run_service import (
    NodeRunNotFoundError,
    RunNotFoundError,
    RunService,
    TaskNotReadyError,
    WorkflowNotFoundError,
)
from agentloom.services.task_service import TaskNotFoundError

router = APIRouter(tags=["runs"])

DatabaseSession = Annotated[AsyncSession, Depends(get_db_session)]


def get_run_service(session: DatabaseSession) -> RunService:
    """Build a run service for the current request transaction."""

    return RunService(
        TaskRepository(session),
        WorkflowRepository(session),
        RunRepository(session),
    )


RunServiceDependency = Annotated[RunService, Depends(get_run_service)]


def error_response(status_code: int, code: str, message: str) -> JSONResponse:
    """Build a root-level standard API error response."""

    error = ApiError(code=code, message=message)
    return JSONResponse(
        status_code=status_code,
        content=error.model_dump(mode="json"),
    )


@router.post(
    "/tasks/{task_id}/runs",
    response_model=RunRead,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ApiError},
        status.HTTP_409_CONFLICT: {"model": ApiError},
    },
)
async def start_run(
    task_id: UUID,
    service: RunServiceDependency,
) -> RunRead | JSONResponse:
    """Queue the latest workflow of a ready task for execution."""

    try:
        return await service.start_run(task_id)
    except TaskNotFoundError:
        return error_response(404, "TASK_NOT_FOUND", "Task not found")
    except TaskNotReadyError:
        return error_response(409, "TASK_NOT_READY", "Task is not ready to run")
    except WorkflowNotFoundError:
        return error_response(409, "WORKFLOW_NOT_FOUND", "Task has no workflow")


@router.get(
    "/runs/{run_id}",
    response_model=RunSnapshot,
    responses={status.HTTP_404_NOT_FOUND: {"model": ApiError}},
)
async def get_run(
    run_id: UUID,
    service: RunServiceDependency,
) -> RunSnapshot | JSONResponse:
    """Return a run, its workflow, and latest node attempts."""

    try:
        return await service.get_run(run_id)
    except RunNotFoundError:
        return error_response(404, "RUN_NOT_FOUND", "Run not found")


@router.get(
    "/node-runs/{node_run_id}/messages",
    response_model=list[AgentMessageRead],
    responses={status.HTTP_404_NOT_FOUND: {"model": ApiError}},
)
async def get_node_messages(
    node_run_id: UUID,
    service: RunServiceDependency,
) -> list[AgentMessageRead] | JSONResponse:
    """Return visible messages for one node attempt."""

    try:
        return await service.get_node_messages(node_run_id)
    except NodeRunNotFoundError:
        return error_response(404, "NODE_RUN_NOT_FOUND", "Node run not found")


__all__ = ["router"]
