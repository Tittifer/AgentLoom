"""Integration tests for historical replay and live SSE notification."""

import asyncio
from collections.abc import AsyncGenerator
from typing import cast
from uuid import UUID, uuid4

from fastapi import Request
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.types import Message, Scope

from agentloom.api.routes.runs import get_run_events, stream_run_events
from agentloom.config import Settings
from agentloom.db.session import DatabaseSessionManager
from agentloom.main import create_app
from agentloom.repositories.events import RunEventRepository
from agentloom.repositories.runs import RunRepository
from agentloom.repositories.tasks import TaskRepository
from agentloom.repositories.workflows import WorkflowRepository
from agentloom.services.event_service import EventService, RunEventNotifier
from agentloom.services.run_service import RunService
from tests.integration.test_run_api import delete_task_graph, seed_ready_task


def make_request(app: object, run_id: UUID) -> Request:
    async def receive() -> Message:
        return {"type": "http.request", "body": b"", "more_body": True}

    scope = cast(
        Scope,
        {
            "type": "http",
            "app": app,
            "method": "GET",
            "path": f"/api/runs/{run_id}/events",
            "headers": [],
        },
    )
    return Request(scope, receive)


async def next_data_event(iterator: AsyncGenerator[str, None]) -> str:
    """Skip legal heartbeats while waiting for the next persisted event."""

    while True:
        chunk = await anext(iterator)
        if not chunk.startswith(":"):
            return chunk


async def test_sse_replays_history_then_delivers_a_new_event() -> None:
    app = create_app(Settings(environment="test", log_level="WARNING"))
    database = cast(DatabaseSessionManager, app.state.database)
    notifier = cast(RunEventNotifier, app.state.run_event_notifier)
    task = await seed_ready_task(database)

    try:
        async with database.session_factory.begin() as session:
            run = await RunService(
                TaskRepository(session),
                WorkflowRepository(session),
                RunRepository(session),
            ).start_run(task.id)
            await EventService(RunEventRepository(session)).append(
                run.id,
                "run.started",
                payload={"status": "running"},
            )

        request = make_request(app, run.id)
        response = await get_run_events(run.id, request, 0)
        assert isinstance(response, StreamingResponse)
        assert response.media_type == "text/event-stream"
        iterator = cast(AsyncGenerator[str, None], response.body_iterator)

        historical = await asyncio.wait_for(anext(iterator), timeout=2)
        assert historical == 'id: 1\nevent: run.started\ndata: {"status":"running"}\n\n'

        pending_event = asyncio.create_task(next_data_event(iterator))
        await asyncio.sleep(0)
        async with database.session_factory.begin() as session:
            await EventService(RunEventRepository(session)).append(
                run.id,
                "node.started",
                node_key="research_apple",
                payload={"status": "running"},
            )
        await notifier.notify(run.id)

        live = await asyncio.wait_for(pending_event, timeout=30)
        assert live == (
            'id: 2\nevent: node.started\ndata: {"status":"running","node_key":"research_apple"}\n\n'
        )
        await iterator.aclose()

        heartbeat_stream = stream_run_events(
            make_request(app, run.id),
            database,
            notifier,
            run.id,
            after=2,
            heartbeat_seconds=0.01,
        )
        assert await asyncio.wait_for(anext(heartbeat_stream), timeout=1) == ": heartbeat\n\n"
        await heartbeat_stream.aclose()

        missing_response = await get_run_events(uuid4(), make_request(app, uuid4()), 0)
        assert isinstance(missing_response, JSONResponse)
        assert missing_response.status_code == 404
    finally:
        await delete_task_graph(database, task.id)
        await database.dispose()
