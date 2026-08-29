"""Task persistence operations."""

from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from agentloom.api.schemas import PaginatedResponse, TaskCreate, TaskRead, TaskSettings
from agentloom.db.models.task import TaskModel
from agentloom.runtime.states import TaskStatus


class TaskRepository:
    """Read and write tasks without exposing ORM instances to callers."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, task: TaskCreate) -> TaskRead:
        """Create a draft task and flush it within the caller's transaction."""

        settings = TaskSettings(
            max_parallel_nodes=task.max_parallel_nodes,
            max_retries=task.max_retries,
        )
        model = TaskModel(
            title=task.title,
            goal=task.goal,
            context=task.context,
            status=TaskStatus.DRAFT,
            settings=settings.model_dump(mode="json"),
        )
        self._session.add(model)
        await self._session.flush()

        return self._to_task_read(model)

    async def get(self, task_id: UUID) -> TaskRead | None:
        """Return one task by ID, or ``None`` when it does not exist."""

        model = await self._session.get(TaskModel, task_id)
        if model is None:
            return None
        return self._to_task_read(model)

    async def list(
        self,
        page: int,
        page_size: int,
        status: TaskStatus | None = None,
    ) -> PaginatedResponse[TaskRead]:
        """Return a deterministic page of tasks, optionally filtered by status."""

        if page < 1:
            raise ValueError("page must be at least 1")
        if not 1 <= page_size <= 100:
            raise ValueError("page_size must be between 1 and 100")

        count_statement = select(func.count()).select_from(TaskModel)
        tasks_statement = select(TaskModel)
        if status is not None:
            count_statement = count_statement.where(TaskModel.status == status)
            tasks_statement = tasks_statement.where(TaskModel.status == status)

        total = await self._session.scalar(count_statement)
        models = (
            await self._session.scalars(
                tasks_statement.order_by(
                    TaskModel.created_at.desc(),
                    TaskModel.id.desc(),
                )
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()

        return PaginatedResponse[TaskRead](
            items=[self._to_task_read(model) for model in models],
            page=page,
            page_size=page_size,
            total=total or 0,
        )

    async def update_status(
        self,
        task_id: UUID,
        old_status: TaskStatus,
        new_status: TaskStatus,
    ) -> TaskRead | None:
        """Atomically update a task only when its current status matches."""

        statement = (
            update(TaskModel)
            .where(
                TaskModel.id == task_id,
                TaskModel.status == old_status,
            )
            .values(status=new_status)
            .returning(TaskModel)
        )
        model = (await self._session.scalars(statement)).one_or_none()
        if model is None:
            return None
        return self._to_task_read(model)

    @staticmethod
    def _to_task_read(model: TaskModel) -> TaskRead:
        settings = TaskSettings.model_validate(model.settings)
        return TaskRead.model_validate(
            {
                "id": model.id,
                "title": model.title,
                "goal": model.goal,
                "context": model.context,
                "status": model.status,
                "max_parallel_nodes": settings.max_parallel_nodes,
                "max_retries": settings.max_retries,
                "created_at": model.created_at,
            }
        )
