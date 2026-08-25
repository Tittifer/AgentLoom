"""PostgreSQL integration tests for Planner task lifecycle and API errors."""

from typing import cast
from uuid import UUID, uuid4

from httpx import ASGITransport, AsyncClient

from agentloom.agents.planner import Planner
from agentloom.api.schemas import ApiError, TaskRead
from agentloom.config import Settings
from agentloom.db.session import DatabaseSessionManager
from agentloom.llm.base import LLMProviderError, LLMResponse
from agentloom.llm.mock import ScriptedMockLLMProvider
from agentloom.main import create_app
from agentloom.repositories.tasks import TaskRepository
from agentloom.repositories.workflows import WorkflowRepository
from agentloom.runtime.states import TaskStatus
from agentloom.runtime.workflow import WorkflowRead
from agentloom.tools.registry import create_builtin_tool_registry
from tests.integration.test_run_api import delete_task_graph


async def create_task(client: AsyncClient, title: str) -> TaskRead:
    response = await client.post(
        "/api/tasks",
        json={
            "title": title,
            "goal": "Compare three products and write a sourced report",
            "context": {"language": "en"},
            "max_parallel_nodes": 3,
            "max_retries": 2,
        },
    )
    assert response.status_code == 201
    return TaskRead.model_validate(response.json())


def scripted_planner(results: list[LLMResponse | Exception]) -> Planner:
    registry = create_builtin_tool_registry()
    return Planner(
        ScriptedMockLLMProvider(results),
        registry.definitions(),
        model="mock/planner",
    )


async def test_plan_api_creates_workflow_and_advances_task_to_ready() -> None:
    app = create_app(Settings(environment="test", log_level="WARNING"))
    database = cast(DatabaseSessionManager, app.state.database)
    task_id: UUID | None = None

    try:
        async with app.router.lifespan_context(app):
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                task = await create_task(client, f"Planner success {uuid4().hex}")
                task_id = task.id

                response = await client.post(f"/api/tasks/{task.id}/plan")
                conflict = await client.post(f"/api/tasks/{task.id}/plan")
                detail = await client.get(f"/api/tasks/{task.id}")

        assert response.status_code == 200
        workflow = WorkflowRead.model_validate(response.json())
        assert workflow.task_id == task.id
        assert [node.key for node in workflow.nodes] == [
            "research_a",
            "research_b",
            "research_c",
            "write_report",
        ]
        assert conflict.status_code == 409
        assert ApiError.model_validate(conflict.json()).code == "TASK_NOT_PLANNABLE"
        assert TaskRead.model_validate(detail.json()).status is TaskStatus.READY
    finally:
        if task_id is not None:
            await delete_task_graph(database, task_id)
        await database.dispose()


async def test_plan_api_marks_task_failed_after_invalid_outputs() -> None:
    invalid = LLMResponse(
        model="mock/planner",
        structured_output={"nodes": [], "final_node": "missing"},
    )
    app = create_app(Settings(environment="test", log_level="WARNING"))
    app.state.planner = scripted_planner([invalid, invalid, invalid])
    database = cast(DatabaseSessionManager, app.state.database)
    task_id: UUID | None = None

    try:
        async with app.router.lifespan_context(app):
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                task = await create_task(client, f"Planner failure {uuid4().hex}")
                task_id = task.id
                response = await client.post(f"/api/tasks/{task.id}/plan")

        assert response.status_code == 422
        error = ApiError.model_validate(response.json())
        assert error.code == "PLANNING_FAILED"
        assert error.details
        async with database.session_factory() as session:
            failed_task = await TaskRepository(session).get(task.id)
            workflow = await WorkflowRepository(session).get_latest_for_task(task.id)
        assert failed_task is not None
        assert failed_task.status is TaskStatus.FAILED
        assert workflow is None
    finally:
        if task_id is not None:
            await delete_task_graph(database, task_id)
        await database.dispose()


async def test_plan_api_returns_not_found_and_provider_errors() -> None:
    app = create_app(Settings(environment="test", log_level="WARNING"))
    app.state.planner = scripted_planner([LLMProviderError("offline")])
    database = cast(DatabaseSessionManager, app.state.database)
    task_id: UUID | None = None

    try:
        async with app.router.lifespan_context(app):
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                missing = await client.post(f"/api/tasks/{uuid4()}/plan")
                task = await create_task(client, f"Planner provider {uuid4().hex}")
                task_id = task.id
                provider_error = await client.post(f"/api/tasks/{task.id}/plan")

        assert missing.status_code == 404
        assert ApiError.model_validate(missing.json()).code == "TASK_NOT_FOUND"
        assert provider_error.status_code == 502
        assert ApiError.model_validate(provider_error.json()).code == "PLANNER_PROVIDER_ERROR"
        async with database.session_factory() as session:
            failed_task = await TaskRepository(session).get(task.id)
        assert failed_task is not None
        assert failed_task.status is TaskStatus.FAILED
    finally:
        if task_id is not None:
            await delete_task_graph(database, task_id)
        await database.dispose()
