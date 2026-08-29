"""Task planning orchestration with short, explicit database transactions."""

from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentloom.agents.planner import (
    Planner,
    PlannerError,
    PlannerGenerationError,
    PlannerIssue,
)
from agentloom.api.schemas import TaskRead
from agentloom.repositories.tasks import TaskRepository
from agentloom.repositories.workflows import InvalidWorkflowError, WorkflowRepository
from agentloom.runtime.states import TaskStatus
from agentloom.runtime.workflow import WorkflowRead
from agentloom.services.task_service import TaskNotFoundError


class TaskNotPlannableError(ValueError):
    """Raised when a task cannot transition from draft to planning."""


class PlanningService:
    """Claim a task, call the planner outside a transaction, and persist the result."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        planner: Planner,
    ) -> None:
        self._session_factory = session_factory
        self._planner = planner
        self._logger = structlog.get_logger(__name__)

    async def plan_task(self, task_id: UUID) -> WorkflowRead:
        """Generate and save one workflow while advancing the task lifecycle."""

        task = await self._claim_task(task_id)
        try:
            plan = await self._planner.plan(
                task.goal,
                task.context,
                max_parallel_nodes=task.max_parallel_nodes,
                max_retries=task.max_retries,
            )
        except PlannerError:
            await self._mark_failed(task.id)
            raise
        except Exception:
            await self._mark_failed(task.id)
            self._logger.exception("planner_execution_failed", task_id=str(task.id))
            raise

        try:
            async with self._session_factory.begin() as session:
                tasks = TaskRepository(session)
                workflow = await WorkflowRepository(session).save(
                    task.id,
                    plan,
                    self._planner.registered_tools,
                )
                ready_task = await tasks.update_status(
                    task.id,
                    TaskStatus.PLANNING,
                    TaskStatus.READY,
                )
                if ready_task is None:
                    raise TaskNotPlannableError
                return workflow
        except InvalidWorkflowError as error:
            await self._mark_failed(task.id)
            issues = [PlannerIssue(path=issue.path, reason=issue.message) for issue in error.errors]
            raise PlannerGenerationError(issues) from error
        except TaskNotPlannableError:
            raise
        except Exception:
            await self._mark_failed(task.id)
            self._logger.exception("workflow_persistence_failed", task_id=str(task.id))
            raise

    async def _claim_task(self, task_id: UUID) -> TaskRead:
        async with self._session_factory.begin() as session:
            tasks = TaskRepository(session)
            task = await tasks.get(task_id)
            if task is None:
                raise TaskNotFoundError(task_id)
            if task.status is not TaskStatus.DRAFT:
                raise TaskNotPlannableError
            claimed = await tasks.update_status(
                task.id,
                TaskStatus.DRAFT,
                TaskStatus.PLANNING,
            )
            if claimed is None:
                raise TaskNotPlannableError
            return claimed

    async def _mark_failed(self, task_id: UUID) -> None:
        async with self._session_factory.begin() as session:
            await TaskRepository(session).update_status(
                task_id,
                TaskStatus.PLANNING,
                TaskStatus.FAILED,
            )


__all__ = ["PlanningService", "TaskNotPlannableError"]
