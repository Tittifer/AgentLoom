"""PostgreSQL integration tests for the Task API."""

from collections.abc import AsyncIterator
from typing import cast
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from agentloom.api.schemas import ApiError, PaginatedResponse, TaskRead
from agentloom.config import Settings
from agentloom.db.models.task import TaskModel
from agentloom.db.session import DatabaseSessionManager
from agentloom.main import create_app
from agentloom.runtime.states import TaskStatus


@pytest.fixture
async def api_client() -> AsyncIterator[tuple[AsyncClient, str]]:
    app = create_app(Settings(environment="test", log_level="WARNING"))
    database = cast(DatabaseSessionManager, app.state.database)
    title_prefix = f"API test {uuid4().hex}"

    async with app.router.lifespan_context(app):
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                yield client, title_prefix
        finally:
            async with database.session_factory() as session:
                await session.execute(
                    delete(TaskModel).where(TaskModel.title.like(f"{title_prefix}%"))
                )
                await session.commit()


async def test_task_api_creates_and_queries_tasks(
    api_client: tuple[AsyncClient, str],
) -> None:
    client, title_prefix = api_client
    baseline_response = await client.get(
        "/api/tasks",
        params={"page": 1, "page_size": 1, "status": TaskStatus.DRAFT},
    )
    baseline = PaginatedResponse[TaskRead].model_validate(baseline_response.json())

    first_response = await client.post(
        "/api/tasks",
        json={
            "title": f"{title_prefix} first",
            "goal": "Compare two implementation options",
            "context": {"source": "integration-test"},
            "max_parallel_nodes": 4,
            "max_retries": 1,
        },
    )
    second_response = await client.post(
        "/api/tasks",
        json={
            "title": f"{title_prefix} second",
            "goal": "Summarize the comparison",
        },
    )

    assert first_response.status_code == 201
    assert second_response.status_code == 201
    first = TaskRead.model_validate(first_response.json())
    second = TaskRead.model_validate(second_response.json())
    assert first.status is TaskStatus.DRAFT
    assert first.context == {"source": "integration-test"}
    assert first.max_parallel_nodes == 4
    assert second.max_parallel_nodes == 3

    detail_response = await client.get(f"/api/tasks/{first.id}")
    assert detail_response.status_code == 200
    assert TaskRead.model_validate(detail_response.json()) == first

    list_response = await client.get(
        "/api/tasks",
        params={"page": 1, "page_size": 2, "status": TaskStatus.DRAFT},
    )
    assert list_response.status_code == 200
    page = PaginatedResponse[TaskRead].model_validate(list_response.json())
    assert page.total == baseline.total + 2
    assert {task.id for task in page.items} == {first.id, second.id}


async def test_task_api_returns_standard_not_found_and_validates_queries(
    api_client: tuple[AsyncClient, str],
) -> None:
    client, _ = api_client

    missing_response = await client.get(f"/api/tasks/{uuid4()}")

    assert missing_response.status_code == 404
    assert ApiError.model_validate(missing_response.json()).model_dump() == {
        "code": "TASK_NOT_FOUND",
        "message": "Task not found",
        "details": [],
    }

    invalid_page_response = await client.get("/api/tasks", params={"page": 0})
    invalid_status_response = await client.get(
        "/api/tasks",
        params={"status": "unknown"},
    )
    assert invalid_page_response.status_code == 422
    assert invalid_status_response.status_code == 422
