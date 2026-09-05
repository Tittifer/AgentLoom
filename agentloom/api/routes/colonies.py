"""Colony lifecycle, conversation, state, and event-stream endpoints."""

import asyncio
import json
from collections.abc import AsyncGenerator
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import JSONResponse, StreamingResponse

from agentloom.api.schemas import ApiError
from agentloom.colony.notifier import ColonyEventNotifier, TransientColonyEvent
from agentloom.colony.runtime import (
    ColonyNotFoundError,
    ColonyRuntime,
    QueenNotFoundError,
    SessionConflictError,
    SessionNotFoundError,
)
from agentloom.colony.schemas import (
    ColonyCreate,
    ColonyEventRead,
    ColonyRead,
    ColonySnapshot,
    MessageCreate,
    MessageRead,
    SessionRead,
    TaskItemRead,
    TrackerEntryRead,
    WorkerRead,
)

router = APIRouter(tags=["colonies"])
EventSequence = Annotated[int, Query(ge=0)]
SSE_HEARTBEAT_SECONDS = 15.0


def get_colony_runtime(request: Request) -> ColonyRuntime:
    return cast(ColonyRuntime, request.app.state.colony_runtime)


RuntimeDependency = Annotated[ColonyRuntime, Depends(get_colony_runtime)]


def error_response(status_code: int, code: str, message: str) -> JSONResponse:
    error = ApiError(code=code, message=message)
    return JSONResponse(status_code=status_code, content=error.model_dump(mode="json"))


def format_sse_event(event: ColonyEventRead) -> str:
    data = {
        **event.payload,
        "colony_id": str(event.colony_id),
        "session_id": str(event.session_id) if event.session_id else None,
        "worker_run_id": str(event.worker_run_id) if event.worker_run_id else None,
        "created_at": event.created_at.isoformat(),
    }
    return (
        f"id: {event.sequence}\n"
        f"event: {event.type}\n"
        f"data: {json.dumps(data, ensure_ascii=False, separators=(',', ':'))}\n\n"
    )


def format_transient_sse_event(event: TransientColonyEvent) -> str:
    return (
        f"event: {event.type}\n"
        f"data: {json.dumps(event.payload, ensure_ascii=False, separators=(',', ':'))}\n\n"
    )


async def stream_colony_events(
    request: Request,
    runtime: ColonyRuntime,
    notifier: ColonyEventNotifier,
    colony_id: UUID,
    after: int,
    heartbeat_seconds: float = SSE_HEARTBEAT_SECONDS,
) -> AsyncGenerator[str, None]:
    cursor = after
    async with notifier.subscribe(colony_id) as updates:
        while not await request.is_disconnected():
            events = await runtime.list_events_after(colony_id, cursor)
            if events is None:
                return
            if events:
                for event in events:
                    if await request.is_disconnected():
                        return
                    cursor = event.sequence
                    yield format_sse_event(event)
                continue
            try:
                update = await asyncio.wait_for(updates.get(), timeout=heartbeat_seconds)
            except TimeoutError:
                yield ": heartbeat\n\n"
                continue
            if update is not None:
                yield format_transient_sse_event(update)


@router.post(
    "/colonies",
    response_model=ColonyRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_colony(
    payload: ColonyCreate,
    runtime: RuntimeDependency,
) -> ColonyRead | JSONResponse:
    try:
        return await runtime.create_colony(payload)
    except QueenNotFoundError:
        return error_response(404, "QUEEN_NOT_FOUND", "Queen 不存在")


@router.get("/colonies", response_model=list[ColonyRead])
async def list_colonies(runtime: RuntimeDependency) -> list[ColonyRead]:
    return await runtime.list_colonies()


@router.delete(
    "/colonies/{colony_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    responses={status.HTTP_404_NOT_FOUND: {"model": ApiError}},
)
async def delete_colony(
    colony_id: UUID,
    runtime: RuntimeDependency,
) -> Response | JSONResponse:
    try:
        await runtime.delete_colony(colony_id)
    except ColonyNotFoundError:
        return error_response(404, "COLONY_NOT_FOUND", "会话不存在")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/colonies/{colony_id}",
    response_model=ColonySnapshot,
    responses={status.HTTP_404_NOT_FOUND: {"model": ApiError}},
)
async def get_colony(
    colony_id: UUID,
    runtime: RuntimeDependency,
) -> ColonySnapshot | JSONResponse:
    try:
        return await runtime.get_snapshot(colony_id)
    except ColonyNotFoundError:
        return error_response(404, "COLONY_NOT_FOUND", "Colony 不存在")


@router.get(
    "/sessions/{session_id}",
    response_model=SessionRead,
    responses={status.HTTP_404_NOT_FOUND: {"model": ApiError}},
)
async def get_session(
    session_id: UUID,
    runtime: RuntimeDependency,
) -> SessionRead | JSONResponse:
    try:
        return await runtime.get_session(session_id)
    except SessionNotFoundError:
        return error_response(404, "SESSION_NOT_FOUND", "会话不存在")


@router.get(
    "/sessions/{session_id}/messages",
    response_model=list[MessageRead],
    responses={status.HTTP_404_NOT_FOUND: {"model": ApiError}},
)
async def list_messages(
    session_id: UUID,
    runtime: RuntimeDependency,
) -> list[MessageRead] | JSONResponse:
    try:
        return await runtime.list_messages(session_id)
    except SessionNotFoundError:
        return error_response(404, "SESSION_NOT_FOUND", "会话不存在")


@router.post(
    "/sessions/{session_id}/messages",
    response_model=MessageRead,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ApiError},
        status.HTTP_409_CONFLICT: {"model": ApiError},
    },
)
async def submit_message(
    session_id: UUID,
    payload: MessageCreate,
    runtime: RuntimeDependency,
) -> MessageRead | JSONResponse:
    try:
        return await runtime.submit_message(session_id, payload.content)
    except SessionNotFoundError:
        return error_response(404, "SESSION_NOT_FOUND", "会话不存在")
    except SessionConflictError as error:
        return error_response(409, "SESSION_CONFLICT", str(error))


@router.get("/colonies/{colony_id}/workers", response_model=list[WorkerRead])
async def list_workers(
    colony_id: UUID,
    runtime: RuntimeDependency,
) -> list[WorkerRead] | JSONResponse:
    try:
        return await runtime.list_workers(colony_id)
    except ColonyNotFoundError:
        return error_response(404, "COLONY_NOT_FOUND", "Colony 不存在")


@router.get("/colonies/{colony_id}/tracker", response_model=list[TrackerEntryRead])
async def list_tracker(
    colony_id: UUID,
    runtime: RuntimeDependency,
    namespace: str | None = None,
) -> list[TrackerEntryRead] | JSONResponse:
    try:
        return await runtime.list_tracker(colony_id, namespace)
    except ColonyNotFoundError:
        return error_response(404, "COLONY_NOT_FOUND", "Colony 不存在")


@router.get("/colonies/{colony_id}/tasks", response_model=list[TaskItemRead])
async def list_tasks(
    colony_id: UUID,
    runtime: RuntimeDependency,
) -> list[TaskItemRead] | JSONResponse:
    try:
        return await runtime.list_tasks(colony_id)
    except ColonyNotFoundError:
        return error_response(404, "COLONY_NOT_FOUND", "Colony 不存在")


@router.get(
    "/colonies/{colony_id}/events",
    response_class=StreamingResponse,
    response_model=None,
)
async def get_colony_events(
    colony_id: UUID,
    request: Request,
    runtime: RuntimeDependency,
    after: EventSequence = 0,
) -> StreamingResponse | JSONResponse:
    if await runtime.list_events_after(colony_id, after) is None:
        return error_response(404, "COLONY_NOT_FOUND", "Colony 不存在")
    notifier = cast(ColonyEventNotifier, request.app.state.colony_event_notifier)
    return StreamingResponse(
        stream_colony_events(request, runtime, notifier, colony_id, after),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


__all__ = ["router"]
