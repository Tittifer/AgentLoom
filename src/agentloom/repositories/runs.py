"""Run and node-attempt persistence operations."""

from collections.abc import Mapping
from uuid import UUID

from pydantic import JsonValue, TypeAdapter
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from agentloom.api.schemas import TaskSettings
from agentloom.db.base import utc_now
from agentloom.db.models.message import AgentMessageModel
from agentloom.db.models.run import NodeRunModel, RunModel
from agentloom.db.models.task import TaskModel
from agentloom.runtime.run import (
    AgentMessageRead,
    NodeExecutionContext,
    NodeRunRead,
    RunRead,
    RunSnapshot,
)
from agentloom.runtime.states import NodeRunStatus, RunStatus, TaskStatus
from agentloom.runtime.workflow import WorkflowRead

JSON_OBJECT_ADAPTER = TypeAdapter(dict[str, JsonValue])
JSON_OBJECT_LIST_ADAPTER = TypeAdapter(list[dict[str, JsonValue]])


class RunRepository:
    """Persist runs and expose complete scheduler snapshots as DTOs."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        task_id: UUID,
        workflow: WorkflowRead,
        run_input: Mapping[str, object],
    ) -> RunRead:
        """Flush a queued run and all initial node attempts atomically."""

        run = RunModel(
            task_id=task_id,
            workflow_id=workflow.id,
            status=RunStatus.QUEUED,
            input=dict(run_input),
            node_runs=[
                NodeRunModel(
                    node_key=node.key,
                    status=NodeRunStatus.PENDING,
                    attempt=1,
                    input={},
                )
                for node in workflow.nodes
            ],
        )
        self._session.add(run)
        await self._session.flush()
        return self._to_run_read(run)

    async def get_snapshot(self, run_id: UUID) -> RunSnapshot | None:
        """Load all state needed by the scheduler and run-detail API."""

        statement = (
            select(RunModel)
            .options(
                selectinload(RunModel.node_runs),
                selectinload(RunModel.task),
            )
            .where(RunModel.id == run_id)
        )
        run = (await self._session.scalars(statement)).one_or_none()
        if run is None:
            return None

        from agentloom.repositories.workflows import WorkflowRepository

        workflow = await WorkflowRepository(self._session).get(run.workflow_id)
        if workflow is None:
            raise RuntimeError(f"Run {run_id} references a missing workflow")

        latest_models: dict[str, NodeRunModel] = {}
        for node_run in sorted(run.node_runs, key=lambda item: item.attempt):
            latest_models[node_run.node_key] = node_run

        missing_node_keys = {node.key for node in workflow.nodes if node.key not in latest_models}
        if missing_node_keys:
            missing = ", ".join(sorted(missing_node_keys))
            raise RuntimeError(f"Run {run_id} is missing node attempts: {missing}")

        node_runs = [self._to_node_run_read(latest_models[node.key]) for node in workflow.nodes]
        node_runs_by_key = {node_run.node_key: node_run for node_run in node_runs}
        upstream_outputs: dict[str, dict[str, dict[str, JsonValue]]] = {}
        for node in workflow.nodes:
            outputs: dict[str, dict[str, JsonValue]] = {}
            for dependency in node.depends_on:
                output = node_runs_by_key[dependency].output
                if output is not None:
                    outputs[dependency] = output
            upstream_outputs[node.key] = outputs

        running_statuses = {NodeRunStatus.RUNNING, NodeRunStatus.REVIEWING}
        current_running_nodes = sum(node_run.status in running_statuses for node_run in node_runs)
        settings = TaskSettings.model_validate(run.task.settings)

        return RunSnapshot(
            run=self._to_run_read(run),
            workflow=workflow,
            node_runs=node_runs,
            upstream_outputs=upstream_outputs,
            current_running_nodes=current_running_nodes,
            max_parallel_nodes=settings.max_parallel_nodes,
        )

    async def claim_runnable_run_ids(self, limit: int = 10) -> list[UUID]:
        """Lock and return queued or running runs for the current scan."""

        statement = (
            select(RunModel.id)
            .where(RunModel.status.in_([RunStatus.QUEUED, RunStatus.RUNNING]))
            .order_by(RunModel.created_at, RunModel.id)
            .with_for_update(skip_locked=True)
            .limit(limit)
        )
        return list((await self._session.scalars(statement)).all())

    async def get_node_execution_context(
        self,
        run_id: UUID,
        node_key: str,
    ) -> NodeExecutionContext | None:
        """Load the latest attempt and bounded inputs required by a worker."""

        snapshot = await self.get_snapshot(run_id)
        if snapshot is None:
            return None
        node = next((item for item in snapshot.workflow.nodes if item.key == node_key), None)
        node_run = next((item for item in snapshot.node_runs if item.node_key == node_key), None)
        if node is None or node_run is None:
            return None

        settings_value = await self._session.scalar(
            select(TaskModel.settings)
            .join(RunModel, RunModel.task_id == TaskModel.id)
            .where(RunModel.id == run_id)
        )
        if settings_value is None:
            raise RuntimeError(f"Run {run_id} references a missing task")
        settings = TaskSettings.model_validate(settings_value)

        goal = snapshot.run.input.get("goal")
        context = snapshot.run.input.get("context", {})
        if not isinstance(goal, str) or not goal.strip():
            raise RuntimeError(f"Run {run_id} has no valid task goal")
        task_context = JSON_OBJECT_ADAPTER.validate_python(context)

        previous_review = await self._session.scalar(
            select(NodeRunModel.review)
            .where(
                NodeRunModel.run_id == run_id,
                NodeRunModel.node_key == node_key,
                NodeRunModel.attempt < node_run.attempt,
                NodeRunModel.review.is_not(None),
            )
            .order_by(NodeRunModel.attempt.desc())
            .limit(1)
        )
        previous_feedback: str | None = None
        if previous_review is not None:
            validated_review = JSON_OBJECT_ADAPTER.validate_python(previous_review)
            feedback = validated_review.get("feedback")
            if isinstance(feedback, str):
                previous_feedback = feedback

        return NodeExecutionContext(
            run_id=run_id,
            node_run_id=node_run.id,
            node_key=node_key,
            attempt=node_run.attempt,
            task_goal=goal,
            task_context=task_context,
            node=node,
            upstream_outputs=snapshot.upstream_outputs[node_key],
            previous_feedback=previous_feedback,
            max_retries=settings.max_retries,
        )

    async def mark_run_running(self, run_id: UUID) -> bool:
        """Move a queued run and its task into running state."""

        task_id = await self._session.scalar(
            update(RunModel)
            .where(RunModel.id == run_id, RunModel.status == RunStatus.QUEUED)
            .values(status=RunStatus.RUNNING, started_at=utc_now())
            .returning(RunModel.task_id)
        )
        if task_id is None:
            return False
        await self._session.execute(
            update(TaskModel)
            .where(TaskModel.id == task_id, TaskModel.status == TaskStatus.READY)
            .values(status=TaskStatus.RUNNING)
        )
        return True

    async def mark_node_running(
        self,
        run_id: UUID,
        node_key: str,
        node_input: Mapping[str, object] | None = None,
    ) -> bool:
        """Move the latest pending or retrying attempt into running state."""

        values: dict[str, object] = {"started_at": utc_now()}
        if node_input is not None:
            values["input"] = dict(node_input)
        return await self._transition_latest_node(
            run_id,
            node_key,
            {NodeRunStatus.PENDING, NodeRunStatus.RETRYING},
            NodeRunStatus.RUNNING,
            **values,
        )

    async def mark_node_reviewing(
        self,
        run_id: UUID,
        node_key: str,
        output: Mapping[str, object] | None = None,
        usage: Mapping[str, object] | None = None,
    ) -> bool:
        """Move the latest running attempt into reviewing state."""

        values: dict[str, object] = {}
        if output is not None:
            values["output"] = dict(output)
        if usage is not None:
            values["usage"] = dict(usage)
        return await self._transition_latest_node(
            run_id,
            node_key,
            {NodeRunStatus.RUNNING},
            NodeRunStatus.REVIEWING,
            **values,
        )

    async def complete_node(
        self,
        run_id: UUID,
        node_key: str,
        output: Mapping[str, object],
        review: Mapping[str, object] | None = None,
    ) -> bool:
        """Persist a reviewed node output and mark the attempt completed."""

        values: dict[str, object] = {
            "output": dict(output),
            "ended_at": utc_now(),
        }
        if review is not None:
            values["review"] = dict(review)
        return await self._transition_latest_node(
            run_id,
            node_key,
            {NodeRunStatus.REVIEWING},
            NodeRunStatus.COMPLETED,
            **values,
        )

    async def fail_node(
        self,
        run_id: UUID,
        node_key: str,
        error: Mapping[str, object],
        review: Mapping[str, object] | None = None,
        usage: Mapping[str, object] | None = None,
    ) -> bool:
        """Persist an execution error and terminate the latest node attempt."""

        values: dict[str, object] = {
            "error": dict(error),
            "ended_at": utc_now(),
        }
        if review is not None:
            values["review"] = dict(review)
        if usage is not None:
            values["usage"] = dict(usage)
        return await self._transition_latest_node(
            run_id,
            node_key,
            {
                NodeRunStatus.PENDING,
                NodeRunStatus.RUNNING,
                NodeRunStatus.REVIEWING,
                NodeRunStatus.RETRYING,
            },
            NodeRunStatus.FAILED,
            **values,
        )

    async def retry_node(
        self,
        run_id: UUID,
        node_key: str,
        review: Mapping[str, object],
    ) -> bool:
        """Finish the reviewed attempt and create its next pending attempt."""

        statement = (
            select(NodeRunModel)
            .where(NodeRunModel.run_id == run_id, NodeRunModel.node_key == node_key)
            .order_by(NodeRunModel.attempt.desc())
            .limit(1)
            .with_for_update()
        )
        current = (await self._session.scalars(statement)).one_or_none()
        if current is None or current.status is not NodeRunStatus.REVIEWING:
            return False
        current.status = NodeRunStatus.RETRYING
        current.review = dict(review)
        current.ended_at = utc_now()
        self._session.add(
            NodeRunModel(
                run_id=run_id,
                node_key=node_key,
                status=NodeRunStatus.PENDING,
                attempt=current.attempt + 1,
                input={},
            )
        )
        await self._session.flush()
        return True

    async def complete_run(self, run_id: UUID, result: Mapping[str, object]) -> bool:
        """Complete a run and its owning task with the final-node result."""

        task_id = await self._session.scalar(
            update(RunModel)
            .where(
                RunModel.id == run_id,
                RunModel.status.in_([RunStatus.QUEUED, RunStatus.RUNNING]),
            )
            .values(status=RunStatus.COMPLETED, result=dict(result), ended_at=utc_now())
            .returning(RunModel.task_id)
        )
        if task_id is None:
            return False
        await self._session.execute(
            update(TaskModel)
            .where(
                TaskModel.id == task_id,
                TaskModel.status.in_([TaskStatus.READY, TaskStatus.RUNNING]),
            )
            .values(status=TaskStatus.COMPLETED)
        )
        return True

    async def fail_run(self, run_id: UUID, error: Mapping[str, object]) -> bool:
        """Fail a run, fail its task, and skip attempts that never started."""

        task_id = await self._session.scalar(
            update(RunModel)
            .where(
                RunModel.id == run_id,
                RunModel.status.in_([RunStatus.QUEUED, RunStatus.RUNNING]),
            )
            .values(status=RunStatus.FAILED, error=dict(error), ended_at=utc_now())
            .returning(RunModel.task_id)
        )
        if task_id is None:
            return False
        await self._session.execute(
            update(NodeRunModel)
            .where(
                NodeRunModel.run_id == run_id,
                NodeRunModel.status.in_([NodeRunStatus.PENDING, NodeRunStatus.RETRYING]),
            )
            .values(status=NodeRunStatus.SKIPPED, ended_at=utc_now())
        )
        await self._session.execute(
            update(TaskModel)
            .where(
                TaskModel.id == task_id,
                TaskModel.status.in_([TaskStatus.READY, TaskStatus.RUNNING]),
            )
            .values(status=TaskStatus.FAILED)
        )
        return True

    async def get_node_messages(
        self,
        node_run_id: UUID,
    ) -> list[AgentMessageRead] | None:
        """Return visible messages for a node attempt, or None if it is missing."""

        exists = await self._session.scalar(
            select(NodeRunModel.id).where(NodeRunModel.id == node_run_id)
        )
        if exists is None:
            return None
        statement = (
            select(AgentMessageModel)
            .where(AgentMessageModel.node_run_id == node_run_id)
            .order_by(AgentMessageModel.created_at, AgentMessageModel.id)
        )
        messages = (await self._session.scalars(statement)).all()
        return [self._to_message_read(message) for message in messages]

    async def get_node_attempts(
        self,
        run_id: UUID,
        node_key: str,
    ) -> list[NodeRunRead] | None:
        """Return every persisted attempt for a run node, or None for a missing run."""

        exists = await self._session.scalar(select(RunModel.id).where(RunModel.id == run_id))
        if exists is None:
            return None
        statement = (
            select(NodeRunModel)
            .where(NodeRunModel.run_id == run_id, NodeRunModel.node_key == node_key)
            .order_by(NodeRunModel.attempt)
        )
        attempts = (await self._session.scalars(statement)).all()
        return [self._to_node_run_read(attempt) for attempt in attempts]

    async def _transition_latest_node(
        self,
        run_id: UUID,
        node_key: str,
        old_statuses: set[NodeRunStatus],
        new_status: NodeRunStatus,
        **values: object,
    ) -> bool:
        latest_node_run_id = (
            select(NodeRunModel.id)
            .where(NodeRunModel.run_id == run_id, NodeRunModel.node_key == node_key)
            .order_by(NodeRunModel.attempt.desc())
            .limit(1)
            .scalar_subquery()
        )
        updated_id = await self._session.scalar(
            update(NodeRunModel)
            .where(
                NodeRunModel.id == latest_node_run_id,
                NodeRunModel.status.in_(old_statuses),
            )
            .values(status=new_status, **values)
            .returning(NodeRunModel.id)
        )
        return updated_id is not None

    @staticmethod
    def _to_run_read(run: RunModel) -> RunRead:
        return RunRead(
            id=run.id,
            task_id=run.task_id,
            workflow_id=run.workflow_id,
            status=run.status,
            input=JSON_OBJECT_ADAPTER.validate_python(run.input),
            result=(
                JSON_OBJECT_ADAPTER.validate_python(run.result) if run.result is not None else None
            ),
            error=(
                JSON_OBJECT_ADAPTER.validate_python(run.error) if run.error is not None else None
            ),
            created_at=run.created_at,
            started_at=run.started_at,
            ended_at=run.ended_at,
        )

    @staticmethod
    def _to_node_run_read(node_run: NodeRunModel) -> NodeRunRead:
        return NodeRunRead(
            id=node_run.id,
            run_id=node_run.run_id,
            node_key=node_run.node_key,
            status=node_run.status,
            attempt=node_run.attempt,
            input=JSON_OBJECT_ADAPTER.validate_python(node_run.input),
            output=(
                JSON_OBJECT_ADAPTER.validate_python(node_run.output)
                if node_run.output is not None
                else None
            ),
            review=(
                JSON_OBJECT_ADAPTER.validate_python(node_run.review)
                if node_run.review is not None
                else None
            ),
            usage=(
                JSON_OBJECT_ADAPTER.validate_python(node_run.usage)
                if node_run.usage is not None
                else None
            ),
            error=(
                JSON_OBJECT_ADAPTER.validate_python(node_run.error)
                if node_run.error is not None
                else None
            ),
            created_at=node_run.created_at,
            started_at=node_run.started_at,
            ended_at=node_run.ended_at,
        )

    @staticmethod
    def _to_message_read(message: AgentMessageModel) -> AgentMessageRead:
        return AgentMessageRead(
            id=message.id,
            node_run_id=message.node_run_id,
            role=message.role,
            content=message.content,
            tool_calls=JSON_OBJECT_LIST_ADAPTER.validate_python(message.tool_calls),
            created_at=message.created_at,
        )


__all__ = ["RunRepository"]
