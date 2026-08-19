"""End-to-end PostgreSQL test for the phase-four Run API and scheduler."""

import asyncio
from typing import cast
from uuid import UUID, uuid4

from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from agentloom.api.schemas import ApiError, TaskCreate, TaskRead
from agentloom.config import Settings
from agentloom.db.models.event import RunEventModel
from agentloom.db.models.message import AgentMessageModel
from agentloom.db.models.run import NodeRunModel, RunModel
from agentloom.db.models.task import TaskModel
from agentloom.db.models.workflow import (
    WorkflowEdgeModel,
    WorkflowModel,
    WorkflowNodeModel,
)
from agentloom.db.session import DatabaseSessionManager
from agentloom.main import create_app
from agentloom.repositories.events import RunEventRepository
from agentloom.repositories.tasks import TaskRepository
from agentloom.repositories.workflows import WorkflowRepository
from agentloom.runtime.run import RunRead, RunSnapshot
from agentloom.runtime.states import NodeRunStatus, RunStatus, TaskStatus
from agentloom.services.event_service import EventService
from tests.fixtures.product_research import (
    PRODUCT_RESEARCH_TOOLS,
    load_product_research_plan,
)


async def seed_ready_task(database: DatabaseSessionManager) -> TaskRead:
    async with database.session_factory.begin() as session:
        tasks = TaskRepository(session)
        task = await tasks.create(
            TaskCreate(
                title=f"Scheduler API test {uuid4().hex}",
                goal="Run the static product research workflow",
                max_parallel_nodes=3,
            )
        )
        await WorkflowRepository(session).save(
            task.id,
            load_product_research_plan(),
            PRODUCT_RESEARCH_TOOLS,
        )
        ready_task = await tasks.update_status(
            task.id,
            TaskStatus.DRAFT,
            TaskStatus.READY,
        )
        assert ready_task is not None
        return ready_task


async def delete_task_graph(database: DatabaseSessionManager, task_id: UUID) -> None:
    async with database.session_factory.begin() as session:
        workflow_ids = select(WorkflowModel.id).where(WorkflowModel.task_id == task_id)
        run_ids = select(RunModel.id).where(RunModel.task_id == task_id)
        node_run_ids = select(NodeRunModel.id).where(NodeRunModel.run_id.in_(run_ids))

        await session.execute(
            delete(AgentMessageModel).where(AgentMessageModel.node_run_id.in_(node_run_ids))
        )
        await session.execute(delete(RunEventModel).where(RunEventModel.run_id.in_(run_ids)))
        await session.execute(delete(NodeRunModel).where(NodeRunModel.run_id.in_(run_ids)))
        await session.execute(delete(RunModel).where(RunModel.task_id == task_id))
        await session.execute(
            delete(WorkflowEdgeModel).where(WorkflowEdgeModel.workflow_id.in_(workflow_ids))
        )
        await session.execute(
            delete(WorkflowNodeModel).where(WorkflowNodeModel.workflow_id.in_(workflow_ids))
        )
        await session.execute(delete(WorkflowModel).where(WorkflowModel.task_id == task_id))
        await session.execute(delete(TaskModel).where(TaskModel.id == task_id))


async def poll_until_terminal(client: AsyncClient, run_id: UUID) -> RunSnapshot:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 60
    last_snapshot: RunSnapshot | None = None
    while loop.time() < deadline:
        response = await client.get(f"/api/runs/{run_id}")
        assert response.status_code == 200
        snapshot = RunSnapshot.model_validate(response.json())
        last_snapshot = snapshot
        if snapshot.is_terminal:
            return snapshot
        await asyncio.sleep(0.05)
    states = (
        [(node.node_key, node.status) for node in last_snapshot.node_runs]
        if last_snapshot is not None
        else []
    )
    raise AssertionError(
        f"Run {run_id} did not reach a terminal state; "
        f"run_status={last_snapshot.run.status if last_snapshot else None}, "
        f"node_states={states}"
    )


async def test_run_api_executes_static_workflow_to_completion() -> None:
    app = create_app(Settings(environment="test", log_level="WARNING"))
    database = cast(DatabaseSessionManager, app.state.database)
    task = await seed_ready_task(database)

    try:
        async with app.router.lifespan_context(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                start_response = await client.post(f"/api/tasks/{task.id}/runs")

                assert start_response.status_code == 202
                run = RunRead.model_validate(start_response.json())
                assert run.status is RunStatus.QUEUED

                snapshot = await poll_until_terminal(client, run.id)

                assert snapshot.run.status is RunStatus.COMPLETED
                assert snapshot.run.result == {
                    "node_key": "write_report",
                    "result": "Mock output for write_report",
                }
                assert all(
                    node_run.status is NodeRunStatus.COMPLETED for node_run in snapshot.node_runs
                )
                assert snapshot.upstream_outputs["write_report"] == {
                    "research_apple": {
                        "node_key": "research_apple",
                        "result": "Mock output for research_apple",
                    },
                    "research_huawei": {
                        "node_key": "research_huawei",
                        "result": "Mock output for research_huawei",
                    },
                    "research_xiaomi": {
                        "node_key": "research_xiaomi",
                        "result": "Mock output for research_xiaomi",
                    },
                }

                async with database.session_factory() as session:
                    events = await EventService(RunEventRepository(session)).list_after(run.id, 0)
                assert [event.sequence for event in events] == list(range(1, 15))
                assert events[0].type == "run.started"
                assert events[-1].type == "run.completed"
                assert [event.type for event in events].count("node.started") == 4
                assert [event.type for event in events].count("node.reviewed") == 4
                assert [event.type for event in events].count("node.completed") == 4

                task_response = await client.get(f"/api/tasks/{task.id}")
                assert task_response.status_code == 200
                assert TaskRead.model_validate(task_response.json()).status is TaskStatus.COMPLETED

                duplicate_start_response = await client.post(f"/api/tasks/{task.id}/runs")
                assert duplicate_start_response.status_code == 409
                assert (
                    ApiError.model_validate(duplicate_start_response.json()).code
                    == "TASK_NOT_READY"
                )

                message_response = await client.get(
                    f"/api/node-runs/{snapshot.node_runs[0].id}/messages"
                )
                assert message_response.status_code == 200
                assert message_response.json() == []

                missing_response = await client.get(f"/api/runs/{uuid4()}")
                assert missing_response.status_code == 404
                assert ApiError.model_validate(missing_response.json()).code == "RUN_NOT_FOUND"
    finally:
        await delete_task_graph(database, task.id)
        await database.dispose()
