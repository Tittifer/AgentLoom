"""PostgreSQL integration tests for the task repository."""

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from agentloom.api.schemas import TaskCreate, TaskRead
from agentloom.config import Settings
from agentloom.db.session import DatabaseSessionManager
from agentloom.repositories.tasks import TaskRepository
from agentloom.runtime.states import TaskStatus


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


def task_payload(index: int = 1) -> TaskCreate:
    return TaskCreate(
        title=f"Research task {index}",
        goal=f"Compare products for scenario {index}",
        context={"index": index, "language": "en"},
        max_parallel_nodes=4,
        max_retries=1,
    )


async def test_create_and_get_return_task_dtos(db_session: AsyncSession) -> None:
    repository = TaskRepository(db_session)

    created = await repository.create(task_payload())
    loaded = await repository.get(created.id)

    assert isinstance(created, TaskRead)
    assert loaded == created
    assert created.status is TaskStatus.DRAFT
    assert created.max_parallel_nodes == 4
    assert created.max_retries == 1


async def test_get_returns_none_for_missing_task(db_session: AsyncSession) -> None:
    repository = TaskRepository(db_session)

    assert await repository.get(uuid4()) is None


async def test_list_returns_deterministic_pages(db_session: AsyncSession) -> None:
    repository = TaskRepository(db_session)
    baseline = await repository.list(page=1, page_size=1)
    created = [await repository.create(task_payload(index)) for index in range(1, 6)]

    first_page = await repository.list(page=1, page_size=2)
    second_page = await repository.list(page=2, page_size=2)
    third_page = await repository.list(page=3, page_size=2)

    assert first_page.total == baseline.total + 5
    assert len(first_page.items) == 2
    assert len(second_page.items) == 2
    assert len(third_page.items) >= 1
    returned_ids = {
        task.id for task in [*first_page.items, *second_page.items, third_page.items[0]]
    }
    assert returned_ids == {task.id for task in created}


async def test_list_filters_by_status(db_session: AsyncSession) -> None:
    repository = TaskRepository(db_session)
    baseline = await repository.list(
        page=1,
        page_size=1,
        status=TaskStatus.PLANNING,
    )
    first = await repository.create(task_payload(1))
    second = await repository.create(task_payload(2))
    await repository.create(task_payload(3))
    await repository.update_status(first.id, TaskStatus.DRAFT, TaskStatus.PLANNING)
    await repository.update_status(second.id, TaskStatus.DRAFT, TaskStatus.PLANNING)

    page = await repository.list(page=1, page_size=10, status=TaskStatus.PLANNING)

    assert page.total == baseline.total + 2
    assert {first.id, second.id} <= {task.id for task in page.items}
    assert all(task.status is TaskStatus.PLANNING for task in page.items)


@pytest.mark.parametrize(
    ("page", "page_size"),
    [(0, 10), (1, 0), (1, 101)],
)
async def test_list_rejects_invalid_pagination(
    db_session: AsyncSession,
    page: int,
    page_size: int,
) -> None:
    repository = TaskRepository(db_session)

    with pytest.raises(ValueError):
        await repository.list(page=page, page_size=page_size)


async def test_update_status_checks_expected_old_status(db_session: AsyncSession) -> None:
    repository = TaskRepository(db_session)
    task = await repository.create(task_payload())

    updated = await repository.update_status(
        task.id,
        TaskStatus.DRAFT,
        TaskStatus.PLANNING,
    )
    stale_update = await repository.update_status(
        task.id,
        TaskStatus.DRAFT,
        TaskStatus.READY,
    )
    loaded = await repository.get(task.id)

    assert updated is not None
    assert updated.status is TaskStatus.PLANNING
    assert stale_update is None
    assert loaded is not None
    assert loaded.status is TaskStatus.PLANNING
