"""Workflow graph persistence operations."""

from collections import defaultdict
from collections.abc import Collection
from uuid import UUID

from pydantic import JsonValue, TypeAdapter
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from agentloom.agents.schemas import WorkflowPlan
from agentloom.db.models.task import TaskModel
from agentloom.db.models.workflow import (
    WorkflowEdgeModel,
    WorkflowModel,
    WorkflowNodeModel,
)
from agentloom.runtime.validator import WorkflowValidationError, validate_workflow
from agentloom.runtime.workflow import WorkflowEdgeRead, WorkflowNodeRead, WorkflowRead

WORKFLOW_READY_STATUS = "ready"
JSON_OBJECT_ADAPTER = TypeAdapter(dict[str, JsonValue])


class InvalidWorkflowError(ValueError):
    """Raised when a workflow cannot be saved because validation failed."""

    def __init__(self, errors: list[WorkflowValidationError]) -> None:
        self.errors = tuple(errors)
        super().__init__("Workflow plan is invalid")


class WorkflowTaskNotFoundError(LookupError):
    """Raised when a workflow's parent task does not exist."""

    def __init__(self, task_id: UUID) -> None:
        self.task_id = task_id
        super().__init__(f"Task {task_id} was not found")


class WorkflowRepository:
    """Persist validated workflow versions without exposing ORM instances."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(
        self,
        task_id: UUID,
        plan: WorkflowPlan,
        registered_tools: Collection[str],
    ) -> WorkflowRead:
        """Validate and flush a new workflow version in the caller's transaction."""

        validation_errors = validate_workflow(plan, registered_tools)
        if validation_errors:
            raise InvalidWorkflowError(validation_errors)

        locked_task_id = await self._session.scalar(
            select(TaskModel.id).where(TaskModel.id == task_id).with_for_update()
        )
        if locked_task_id is None:
            raise WorkflowTaskNotFoundError(task_id)

        latest_version = await self._session.scalar(
            select(func.max(WorkflowModel.version)).where(WorkflowModel.task_id == task_id)
        )
        workflow = WorkflowModel(
            task_id=task_id,
            version=(latest_version or 0) + 1,
            status=WORKFLOW_READY_STATUS,
            final_node_key=plan.final_node,
            nodes=[
                WorkflowNodeModel(
                    node_key=node.key,
                    name=node.name,
                    role=node.role,
                    description=node.description,
                    prompt=node.system_prompt,
                    tools=list(node.tools),
                    output_schema=dict(node.output_schema),
                    review_criteria=node.review_criteria,
                    sort_order=index,
                )
                for index, node in enumerate(plan.nodes)
            ],
            edges=[],
        )
        self._session.add(workflow)
        await self._session.flush()

        workflow.edges.extend(
            WorkflowEdgeModel(
                source_node_key=dependency,
                target_node_key=node.key,
            )
            for node in plan.nodes
            for dependency in node.depends_on
        )
        await self._session.flush()

        return self._to_workflow_read(workflow)

    async def get(self, workflow_id: UUID) -> WorkflowRead | None:
        """Return a complete workflow by ID."""

        statement = (
            select(WorkflowModel)
            .options(
                selectinload(WorkflowModel.nodes),
                selectinload(WorkflowModel.edges),
            )
            .where(WorkflowModel.id == workflow_id)
        )
        workflow = (await self._session.scalars(statement)).one_or_none()
        if workflow is None:
            return None
        return self._to_workflow_read(workflow)

    async def get_latest_for_task(self, task_id: UUID) -> WorkflowRead | None:
        """Return the newest workflow version for a task."""

        statement = (
            select(WorkflowModel)
            .options(
                selectinload(WorkflowModel.nodes),
                selectinload(WorkflowModel.edges),
            )
            .where(WorkflowModel.task_id == task_id)
            .order_by(WorkflowModel.version.desc(), WorkflowModel.id.desc())
            .limit(1)
        )
        workflow = (await self._session.scalars(statement)).one_or_none()
        if workflow is None:
            return None
        return self._to_workflow_read(workflow)

    @staticmethod
    def _to_workflow_read(workflow: WorkflowModel) -> WorkflowRead:
        dependencies: defaultdict[str, list[str]] = defaultdict(list)
        for edge in workflow.edges:
            dependencies[edge.target_node_key].append(edge.source_node_key)

        nodes = [
            WorkflowNodeRead(
                id=node.id,
                key=node.node_key,
                name=node.name,
                role=node.role,
                description=node.description,
                system_prompt=node.prompt,
                depends_on=sorted(dependencies[node.node_key]),
                tools=node.tools,
                output_schema=JSON_OBJECT_ADAPTER.validate_python(node.output_schema),
                review_criteria=node.review_criteria,
                sort_order=node.sort_order,
            )
            for node in sorted(workflow.nodes, key=lambda item: (item.sort_order, item.node_key))
        ]
        edges = [
            WorkflowEdgeRead(
                id=edge.id,
                source_node_key=edge.source_node_key,
                target_node_key=edge.target_node_key,
            )
            for edge in sorted(
                workflow.edges,
                key=lambda item: (item.source_node_key, item.target_node_key),
            )
        ]
        return WorkflowRead(
            id=workflow.id,
            task_id=workflow.task_id,
            version=workflow.version,
            status=workflow.status,
            final_node=workflow.final_node_key,
            created_at=workflow.created_at,
            nodes=nodes,
            edges=edges,
        )


__all__ = [
    "InvalidWorkflowError",
    "WorkflowRepository",
    "WorkflowTaskNotFoundError",
]
