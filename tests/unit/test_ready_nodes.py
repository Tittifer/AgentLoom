"""Tests for pure DAG readiness calculation."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from agentloom.runtime.run import NodeRunRead, RunRead, RunSnapshot
from agentloom.runtime.scheduler import find_ready_nodes
from agentloom.runtime.states import NodeRunStatus, RunStatus
from agentloom.runtime.workflow import WorkflowEdgeRead, WorkflowNodeRead, WorkflowRead
from tests.fixtures.product_research import load_product_research_plan


def build_snapshot(
    statuses: dict[str, NodeRunStatus],
    *,
    run_status: RunStatus = RunStatus.RUNNING,
    max_parallel_nodes: int = 3,
) -> RunSnapshot:
    plan = load_product_research_plan()
    now = datetime.now(UTC)
    run_id = uuid4()
    task_id = uuid4()
    workflow_id = uuid4()
    nodes = [
        WorkflowNodeRead(
            id=uuid4(),
            key=node.key,
            name=node.name,
            role=node.role,
            description=node.description,
            system_prompt=node.system_prompt,
            depends_on=node.depends_on,
            tools=node.tools,
            output_schema=node.output_schema,
            review_criteria=node.review_criteria,
            sort_order=index,
        )
        for index, node in enumerate(plan.nodes)
    ]
    edges = [
        WorkflowEdgeRead(
            id=uuid4(),
            source_node_key=dependency,
            target_node_key=node.key,
        )
        for node in plan.nodes
        for dependency in node.depends_on
    ]
    node_runs = [make_node_run(run_id, node.key, statuses[node.key], now) for node in nodes]
    running_count = sum(
        node_run.status in {NodeRunStatus.RUNNING, NodeRunStatus.REVIEWING}
        for node_run in node_runs
    )
    return RunSnapshot(
        run=RunRead(
            id=run_id,
            task_id=task_id,
            workflow_id=workflow_id,
            status=run_status,
            input={},
            result=None,
            error=None,
            created_at=now,
            started_at=now,
            ended_at=None,
        ),
        workflow=WorkflowRead(
            id=workflow_id,
            task_id=task_id,
            version=1,
            status="ready",
            final_node=plan.final_node,
            created_at=now,
            nodes=nodes,
            edges=edges,
        ),
        node_runs=node_runs,
        upstream_outputs={node.key: {} for node in nodes},
        current_running_nodes=running_count,
        max_parallel_nodes=max_parallel_nodes,
    )


def make_node_run(
    run_id: UUID,
    node_key: str,
    status: NodeRunStatus,
    created_at: datetime,
) -> NodeRunRead:
    return NodeRunRead(
        id=uuid4(),
        run_id=run_id,
        node_key=node_key,
        status=status,
        attempt=1,
        input={},
        output={"node_key": node_key} if status is NodeRunStatus.COMPLETED else None,
        review=None,
        usage=None,
        error=None,
        created_at=created_at,
        started_at=None,
        ended_at=None,
    )


def initial_statuses() -> dict[str, NodeRunStatus]:
    return {
        "research_apple": NodeRunStatus.PENDING,
        "research_huawei": NodeRunStatus.PENDING,
        "research_xiaomi": NodeRunStatus.PENDING,
        "write_report": NodeRunStatus.PENDING,
    }


def test_initial_research_nodes_are_ready_before_report() -> None:
    ready = find_ready_nodes(build_snapshot(initial_statuses()))

    assert [node.key for node in ready] == [
        "research_apple",
        "research_huawei",
        "research_xiaomi",
    ]


def test_report_waits_until_all_research_nodes_complete() -> None:
    statuses = initial_statuses()
    statuses["research_apple"] = NodeRunStatus.COMPLETED
    statuses["research_huawei"] = NodeRunStatus.COMPLETED

    ready = find_ready_nodes(build_snapshot(statuses))

    assert [node.key for node in ready] == ["research_xiaomi"]

    statuses["research_xiaomi"] = NodeRunStatus.COMPLETED
    ready = find_ready_nodes(build_snapshot(statuses))
    assert [node.key for node in ready] == ["write_report"]


def test_ready_nodes_respect_remaining_concurrency() -> None:
    statuses = initial_statuses()
    statuses["research_apple"] = NodeRunStatus.RUNNING

    ready = find_ready_nodes(build_snapshot(statuses, max_parallel_nodes=2))

    assert [node.key for node in ready] == ["research_huawei"]


def test_terminal_run_has_no_ready_nodes() -> None:
    snapshot = build_snapshot(initial_statuses(), run_status=RunStatus.CANCELLED)

    assert find_ready_nodes(snapshot) == []
