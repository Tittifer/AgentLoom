"""PostgreSQL integration tests for run creation and snapshots."""

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from agentloom.api.schemas import TaskCreate, TaskRead
from agentloom.config import Settings
from agentloom.db.models.run import RunModel
from agentloom.db.session import DatabaseSessionManager
from agentloom.repositories.runs import RunRepository
from agentloom.repositories.tasks import TaskRepository
from agentloom.repositories.workflows import WorkflowRepository
from agentloom.runtime.states import NodeRunStatus, RunStatus, TaskStatus
from agentloom.runtime.workflow import WorkflowRead
from agentloom.services.run_service import RunService, TaskNotReadyError
from tests.fixtures.product_research import (
    PRODUCT_RESEARCH_TOOLS,
    load_product_research_plan,
)


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    database = DatabaseSessionManager(Settings().database_url)

    try:
        async with database.session_factory() as session:
            try:
                yield session
            finally:
                await session.rollback()
    finally:
        await database.dispose()


async def create_task_and_workflow(
    session: AsyncSession,
    *,
    ready: bool,
) -> tuple[TaskRead, WorkflowRead]:
    tasks = TaskRepository(session)
    task = await tasks.create(
        TaskCreate(
            title="Run creation test",
            goal="Execute the static product research workflow",
            context={"language": "en"},
        )
    )
    workflow = await WorkflowRepository(session).save(
        task.id,
        load_product_research_plan(),
        PRODUCT_RESEARCH_TOOLS,
    )
    if ready:
        updated = await tasks.update_status(task.id, TaskStatus.DRAFT, TaskStatus.READY)
        assert updated is not None
        task = updated
    return task, workflow


def create_run_service(session: AsyncSession) -> RunService:
    return RunService(
        TaskRepository(session),
        WorkflowRepository(session),
        RunRepository(session),
    )


async def test_run_creation_requires_ready_task_and_creates_initial_snapshot(
    db_session: AsyncSession,
) -> None:
    task, workflow = await create_task_and_workflow(db_session, ready=False)
    service = create_run_service(db_session)

    with pytest.raises(TaskNotReadyError):
        await service.start_run(task.id)

    run_count = await db_session.scalar(
        select(func.count()).select_from(RunModel).where(RunModel.task_id == task.id)
    )
    assert run_count == 0

    updated = await TaskRepository(db_session).update_status(
        task.id,
        TaskStatus.DRAFT,
        TaskStatus.READY,
    )
    assert updated is not None

    run = await service.start_run(task.id)
    snapshot = await RunRepository(db_session).get_snapshot(run.id)
    running_task = await TaskRepository(db_session).get(task.id)

    assert run.status is RunStatus.QUEUED
    assert run.workflow_id == workflow.id
    assert run.input == {
        "goal": task.goal,
        "context": {"language": "en"},
    }
    assert snapshot is not None
    assert len(snapshot.node_runs) == 4
    assert all(node.status is NodeRunStatus.PENDING for node in snapshot.node_runs)
    assert all(node.attempt == 1 for node in snapshot.node_runs)
    assert snapshot.current_running_nodes == 0
    assert snapshot.max_parallel_nodes == 3
    assert snapshot.upstream_outputs["write_report"] == {}
    assert running_task is not None
    assert running_task.status is TaskStatus.RUNNING

    with pytest.raises(TaskNotReadyError):
        await service.start_run(task.id)
    run_count = await db_session.scalar(
        select(func.count()).select_from(RunModel).where(RunModel.task_id == task.id)
    )
    assert run_count == 1


async def test_failed_run_creation_leaves_no_partial_rows(
    db_session: AsyncSession,
) -> None:
    task, workflow = await create_task_and_workflow(db_session, ready=True)
    duplicate_node = workflow.nodes[0].model_copy(update={"id": uuid4()})
    invalid_workflow = workflow.model_copy(update={"nodes": [*workflow.nodes, duplicate_node]})

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await RunRepository(db_session).create(task.id, invalid_workflow, {})

    run_count = await db_session.scalar(
        select(func.count()).select_from(RunModel).where(RunModel.task_id == task.id)
    )
    assert run_count == 0
