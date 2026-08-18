"""PostgreSQL integration tests for workflow persistence."""

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from agentloom.agents.schemas import WorkflowPlan
from agentloom.api.schemas import TaskCreate
from agentloom.config import Settings
from agentloom.db.session import DatabaseSessionManager
from agentloom.repositories.tasks import TaskRepository
from agentloom.repositories.workflows import (
    InvalidWorkflowError,
    WorkflowRepository,
    WorkflowTaskNotFoundError,
)
from agentloom.runtime.validator import validate_workflow
from agentloom.runtime.workflow import WorkflowRead
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


def assert_workflow_matches_plan(workflow: WorkflowRead, plan: WorkflowPlan) -> None:
    assert workflow.final_node == plan.final_node
    assert workflow.status == "ready"
    assert len(workflow.nodes) == len(plan.nodes)

    stored_nodes = {node.key: node for node in workflow.nodes}
    for sort_order, planned_node in enumerate(plan.nodes):
        stored_node = stored_nodes[planned_node.key]
        assert stored_node.name == planned_node.name
        assert stored_node.role == planned_node.role
        assert stored_node.description == planned_node.description
        assert stored_node.system_prompt == planned_node.system_prompt
        assert stored_node.depends_on == sorted(planned_node.depends_on)
        assert stored_node.tools == planned_node.tools
        assert stored_node.output_schema == planned_node.output_schema
        assert stored_node.review_criteria == planned_node.review_criteria
        assert stored_node.sort_order == sort_order

    expected_edges = {
        (dependency, node.key) for node in plan.nodes for dependency in node.depends_on
    }
    stored_edges = {(edge.source_node_key, edge.target_node_key) for edge in workflow.edges}
    assert stored_edges == expected_edges


async def test_static_workflow_validates_and_round_trips(
    db_session: AsyncSession,
) -> None:
    task = await TaskRepository(db_session).create(
        TaskCreate(
            title="Static product research",
            goal="Compare Apple, Huawei, and Xiaomi",
        )
    )
    plan = load_product_research_plan()
    repository = WorkflowRepository(db_session)

    assert validate_workflow(plan, PRODUCT_RESEARCH_TOOLS) == []

    created = await repository.save(task.id, plan, PRODUCT_RESEARCH_TOOLS)
    loaded = await repository.get(created.id)

    assert loaded is not None
    assert isinstance(loaded, WorkflowRead)
    assert loaded == created
    assert_workflow_matches_plan(loaded, plan)


async def test_workflow_versions_and_latest_query(db_session: AsyncSession) -> None:
    task = await TaskRepository(db_session).create(
        TaskCreate(title="Versioned workflow", goal="Test workflow versions")
    )
    plan = load_product_research_plan()
    repository = WorkflowRepository(db_session)

    first = await repository.save(task.id, plan, PRODUCT_RESEARCH_TOOLS)
    second = await repository.save(task.id, plan, PRODUCT_RESEARCH_TOOLS)
    latest = await repository.get_latest_for_task(task.id)

    assert first.version == 1
    assert second.version == 2
    assert latest == second


async def test_repository_rejects_invalid_workflow_before_writing(
    db_session: AsyncSession,
) -> None:
    task = await TaskRepository(db_session).create(
        TaskCreate(title="Invalid workflow", goal="Reject invalid workflow")
    )
    plan = load_product_research_plan()
    repository = WorkflowRepository(db_session)

    with pytest.raises(InvalidWorkflowError) as error:
        await repository.save(task.id, plan, registered_tools=set())

    assert {issue.code for issue in error.value.errors} == {"tool_not_registered"}
    assert await repository.get_latest_for_task(task.id) is None


async def test_repository_rejects_missing_parent_task(db_session: AsyncSession) -> None:
    repository = WorkflowRepository(db_session)

    with pytest.raises(WorkflowTaskNotFoundError):
        await repository.save(
            uuid4(),
            load_product_research_plan(),
            PRODUCT_RESEARCH_TOOLS,
        )
