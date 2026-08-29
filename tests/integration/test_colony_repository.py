"""PostgreSQL integration tests for the Colony aggregate repository."""

from uuid import uuid4

import pytest
from sqlalchemy import delete

from agentloom.colony.schemas import TaskItemCreate, TrackerUpsert, WorkerTask
from agentloom.config import Settings
from agentloom.db.models.colony import ColonyModel
from agentloom.db.session import DatabaseSessionManager
from agentloom.llm.base import LLMMessage
from agentloom.repositories.colonies import ColonyRepository, TrackerVersionConflictError
from agentloom.runtime.states import SessionStatus, TaskItemStatus, WorkerStatus


async def test_colony_repository_persists_shared_runtime_state() -> None:
    database = DatabaseSessionManager(Settings().database_url)
    name = f"Repository test {uuid4().hex}"
    colony_id = None
    try:
        async with database.session_factory.begin() as session:
            repository = ColonyRepository(session)
            colony, queen = await repository.create(name, "", "general", "mock/schema", {})
            colony_id = colony.id
            assert (await repository.get(colony.id)) == colony
            assert (await repository.get_queen_session(colony.id)) == queen
            assert any(item.id == colony.id for item in await repository.list_colonies())

            await repository.set_session_status(queen.id, SessionStatus.QUEUED)
            user_message = await repository.append_message(
                queen.id,
                LLMMessage(role="user", content="开始"),
            )
            assert user_message is not None and user_message.sequence == 1
            assert len(await repository.list_messages(queen.id) or []) == 1

            workers = await repository.create_workers(
                queen.id,
                [WorkerTask(task="并行研究", data={"topic": "A"})],
                30,
            )
            running = await repository.mark_worker_running(workers[0].id)
            assert running is not None and running.status is WorkerStatus.RUNNING
            assert await repository.get_worker_for_session(running.worker_session_id) == running
            completed = await repository.finish_worker(
                running.worker_session_id,
                WorkerStatus.COMPLETED,
                report={"summary": "完成"},
            )
            assert completed is not None and completed.report == {"summary": "完成"}

            first = await repository.upsert_tracker(
                colony.id,
                queen.id,
                TrackerUpsert(namespace="research", entry_key="A", data={"score": 1}),
            )
            second = await repository.upsert_tracker(
                colony.id,
                queen.id,
                TrackerUpsert(
                    namespace="research",
                    entry_key="A",
                    status="done",
                    data={"score": 2},
                    expected_version=first.version,
                ),
            )
            assert second.version == 2
            with pytest.raises(TrackerVersionConflictError):
                await repository.upsert_tracker(
                    colony.id,
                    queen.id,
                    TrackerUpsert(
                        namespace="research",
                        entry_key="A",
                        expected_version=1,
                    ),
                )

            task = await repository.create_task_item(
                colony.id,
                queen.id,
                TaskItemCreate(title="汇总结果"),
            )
            updated = await repository.update_task_status(task.id, TaskItemStatus.COMPLETED)
            assert updated is not None and updated.status is TaskItemStatus.COMPLETED
            assert [item.id for item in await repository.list_tasks(colony.id)] == [task.id]

            event = await repository.append_event(
                colony.id,
                "test.completed",
                session_id=queen.id,
                payload={"ok": True},
            )
            assert event is not None
            assert await repository.list_events_after(colony.id, event.sequence - 1) == [event]
    finally:
        if colony_id is not None:
            async with database.session_factory.begin() as session:
                await session.execute(delete(ColonyModel).where(ColonyModel.id == colony_id))
        await database.dispose()
