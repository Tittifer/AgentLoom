"""PostgreSQL API tests for cancellation and failed-run retry."""

from typing import cast

from httpx import ASGITransport, AsyncClient

from agentloom.api.schemas import ApiError
from agentloom.config import Settings
from agentloom.db.session import DatabaseSessionManager
from agentloom.main import create_app
from agentloom.repositories.events import RunEventRepository
from agentloom.repositories.runs import RunRepository
from agentloom.repositories.tasks import TaskRepository
from agentloom.repositories.workflows import WorkflowRepository
from agentloom.runtime.run import RunRead
from agentloom.runtime.states import NodeRunStatus, RunStatus, TaskStatus
from agentloom.services.event_service import EventService
from agentloom.services.run_service import RunService
from tests.integration.test_run_api import delete_task_graph, seed_ready_task


async def start_seeded_run(database: DatabaseSessionManager) -> RunRead:
    task = await seed_ready_task(database)
    async with database.session_factory.begin() as session:
        return await RunService(
            TaskRepository(session),
            WorkflowRepository(session),
            RunRepository(session),
        ).start_run(task.id)


async def test_cancel_api_cancels_unfinished_nodes_and_rejects_late_results() -> None:
    app = create_app(Settings(environment="test", log_level="WARNING"))
    database = cast(DatabaseSessionManager, app.state.database)
    run = await start_seeded_run(database)

    try:
        async with database.session_factory.begin() as session:
            repository = RunRepository(session)
            assert await repository.mark_run_running(run.id)
            assert await repository.mark_node_running(run.id, "research_apple")

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(f"/api/runs/{run.id}/cancel")
            duplicate = await client.post(f"/api/runs/{run.id}/cancel")

        assert response.status_code == 200
        assert RunRead.model_validate(response.json()).status is RunStatus.CANCELLED
        assert duplicate.status_code == 409
        assert ApiError.model_validate(duplicate.json()).code == "RUN_NOT_CANCELLABLE"

        async with database.session_factory.begin() as session:
            repository = RunRepository(session)
            assert not await repository.mark_node_reviewing(
                run.id,
                "research_apple",
                {"summary": "late", "sources": ["source"]},
            )
            snapshot = await repository.get_snapshot(run.id)
            task = await TaskRepository(session).get(run.task_id)
            events = await EventService(RunEventRepository(session)).list_after(run.id, 0)

        assert snapshot is not None
        assert all(node.status is NodeRunStatus.CANCELLED for node in snapshot.node_runs)
        assert task is not None and task.status is TaskStatus.CANCELLED
        assert events[-1].type == "run.cancelled"
    finally:
        await delete_task_graph(database, run.task_id)
        await database.dispose()


async def test_retry_api_creates_a_new_run_without_mutating_failed_history() -> None:
    app = create_app(Settings(environment="test", log_level="WARNING"))
    database = cast(DatabaseSessionManager, app.state.database)
    original = await start_seeded_run(database)

    try:
        async with database.session_factory.begin() as session:
            repository = RunRepository(session)
            assert await repository.mark_run_running(original.id)
            assert await repository.fail_run(original.id, {"code": "TEST_FAILURE"})

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(f"/api/runs/{original.id}/retry")
            duplicate = await client.post(f"/api/runs/{original.id}/retry")

        assert response.status_code == 202
        retried = RunRead.model_validate(response.json())
        assert retried.id != original.id
        assert retried.workflow_id == original.workflow_id
        assert retried.input == original.input
        assert retried.status is RunStatus.QUEUED
        assert duplicate.status_code == 409
        assert ApiError.model_validate(duplicate.json()).code == "RUN_NOT_RETRYABLE"

        async with database.session_factory() as session:
            original_snapshot = await RunRepository(session).get_snapshot(original.id)
            retried_snapshot = await RunRepository(session).get_snapshot(retried.id)
        assert original_snapshot is not None
        assert original_snapshot.run.status is RunStatus.FAILED
        assert retried_snapshot is not None
        assert all(node.attempt == 1 for node in retried_snapshot.node_runs)
    finally:
        await delete_task_graph(database, original.task_id)
        await database.dispose()
