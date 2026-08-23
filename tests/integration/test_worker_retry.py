"""PostgreSQL integration test for persisted Worker retries."""

from sqlalchemy import select

from agentloom.agents.reviewer import DeterministicReviewer
from agentloom.agents.worker import DatabaseWorkerStore, Worker
from agentloom.config import Settings
from agentloom.db.models.run import NodeRunModel
from agentloom.db.session import DatabaseSessionManager
from agentloom.llm.base import LLMResponse
from agentloom.llm.mock import ScriptedMockLLMProvider
from agentloom.repositories.events import RunEventRepository
from agentloom.repositories.runs import RunRepository
from agentloom.repositories.tasks import TaskRepository
from agentloom.repositories.workflows import WorkflowRepository
from agentloom.runtime.states import NodeRunStatus
from agentloom.services.event_service import EventService, RunEventNotifier
from agentloom.services.run_service import RunService
from agentloom.tools.registry import create_builtin_tool_registry
from tests.integration.test_run_api import delete_task_graph, seed_ready_task


async def test_worker_retry_creates_a_second_persisted_attempt() -> None:
    database = DatabaseSessionManager(Settings().database_url)
    task = await seed_ready_task(database)

    try:
        async with database.session_factory.begin() as session:
            run = await RunService(
                TaskRepository(session),
                WorkflowRepository(session),
                RunRepository(session),
            ).start_run(task.id)

        notifier = RunEventNotifier()
        worker = Worker(
            DatabaseWorkerStore(database.session_factory, notifier),
            ScriptedMockLLMProvider(
                [
                    LLMResponse(
                        model="mock/test",
                        structured_output={"summary": "", "sources": []},
                    ),
                    LLMResponse(
                        model="mock/test",
                        structured_output={"summary": "valid", "sources": ["source"]},
                    ),
                ]
            ),
            DeterministicReviewer(),
            create_builtin_tool_registry(),
            model="mock/test",
        )

        await worker.execute(run.id, "research_apple")

        async with database.session_factory() as session:
            attempts = list(
                (
                    await session.scalars(
                        select(NodeRunModel)
                        .where(
                            NodeRunModel.run_id == run.id,
                            NodeRunModel.node_key == "research_apple",
                        )
                        .order_by(NodeRunModel.attempt)
                    )
                ).all()
            )
            events = await EventService(RunEventRepository(session)).list_after(run.id, 0)
            first_messages = await RunRepository(session).get_node_messages(attempts[0].id)
            second_messages = await RunRepository(session).get_node_messages(attempts[1].id)

        assert [attempt.attempt for attempt in attempts] == [1, 2]
        assert [attempt.status for attempt in attempts] == [
            NodeRunStatus.RETRYING,
            NodeRunStatus.COMPLETED,
        ]
        assert attempts[0].review is not None
        assert attempts[0].review["decision"] == "retry"
        assert attempts[1].review is not None
        assert attempts[1].review["decision"] == "accept"
        assert [event.sequence for event in events] == list(range(1, 9))
        assert [event.type for event in events].count("node.retrying") == 1
        assert first_messages is not None
        assert second_messages is not None
        assert [message.role for message in first_messages] == [
            "system",
            "user",
            "assistant",
            "reviewer",
        ]
        assert [message.role for message in second_messages] == [
            "system",
            "user",
            "assistant",
            "reviewer",
        ]
    finally:
        await delete_task_graph(database, task.id)
        await database.dispose()
