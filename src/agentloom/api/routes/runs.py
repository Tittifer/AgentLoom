"""Run, node-attempt, and event-stream HTTP endpoints."""

import json
from collections.abc import AsyncGenerator
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from agentloom.api.schemas import ApiError
from agentloom.db.session import DatabaseSessionManager, get_db_session
from agentloom.repositories.events import RunEventRepository
from agentloom.repositories.runs import RunRepository
from agentloom.repositories.tasks import TaskRepository
from agentloom.repositories.workflows import WorkflowRepository
from agentloom.runtime.run import AgentMessageRead, RunEventRead, RunRead, RunSnapshot
from agentloom.services.event_service import EventService, RunEventNotifier
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
EventSequence = Annotated[int, Query(ge=0)]

SSE_HEARTBEAT_SECONDS = 15.0


def error_response(status_code: int, code: str, message: str) -> JSONResponse:
    """Build a root-level standard API error response."""

    error = ApiError(code=code, message=message)
    return JSONResponse(
        status_code=status_code,
        content=error.model_dump(mode="json"),
    )


def format_sse_event(event: RunEventRead) -> str:
    """Serialize one persisted event using the SSE wire format."""

    data = dict(event.payload)
    if event.node_key is not None:
        data["node_key"] = event.node_key
    return (
        f"id: {event.sequence}\n"
        f"event: {event.type}\n"
        f"data: {json.dumps(data, ensure_ascii=False, separators=(',', ':'))}\n\n"
    )


async def stream_run_events(
    request: Request,
    database: DatabaseSessionManager,
    notifier: RunEventNotifier,
    run_id: UUID,
    after: int,
    heartbeat_seconds: float = SSE_HEARTBEAT_SECONDS,
) -> AsyncGenerator[str, None]:
    """Replay stored events, then wait for committed local changes."""

    cursor = after
    while not await request.is_disconnected():
        observed_version = notifier.version(run_id)
        async with database.session_factory() as session:
            events = await EventService(RunEventRepository(session)).list_after(run_id, cursor)

        if events:
            for event in events:
                if await request.is_disconnected():
                    return
                cursor = event.sequence
                yield format_sse_event(event)
            continue

        if await request.is_disconnected():
            return
        changed = await notifier.wait_for_change(
            run_id,
            observed_version,
            timeout=heartbeat_seconds,
        )
        if not changed:
            yield ": heartbeat\n\n"


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
    "/runs/{run_id}/events",
    response_class=StreamingResponse,
    response_model=None,
    responses={status.HTTP_404_NOT_FOUND: {"model": ApiError}},
)
async def get_run_events(
    run_id: UUID,
    request: Request,
    after: EventSequence = 0,
) -> StreamingResponse | JSONResponse:
    """Stream replayable run events after the supplied sequence."""

    database = cast(DatabaseSessionManager, request.app.state.database)
    notifier = cast(RunEventNotifier, request.app.state.run_event_notifier)
    async with database.session_factory() as session:
        exists = await EventService(RunEventRepository(session)).run_exists(run_id)
    if not exists:
        return error_response(404, "RUN_NOT_FOUND", "Run not found")

    return StreamingResponse(
        stream_run_events(request, database, notifier, run_id, after),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


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
