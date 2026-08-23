"""PostgreSQL integration tests for ordered run events."""

import asyncio

from pydantic import JsonValue

from agentloom.agents.prompts import build_worker_messages
from agentloom.agents.reviewer import DeterministicReviewer
from agentloom.agents.worker import DatabaseWorkerStore
from agentloom.config import Settings
from agentloom.db.base import JsonObject
from agentloom.db.session import DatabaseSessionManager
from agentloom.repositories.events import RunEventRepository
from agentloom.repositories.runs import RunRepository
from agentloom.repositories.tasks import TaskRepository
from agentloom.repositories.workflows import WorkflowRepository
from agentloom.runtime.states import NodeRunStatus
from agentloom.services.event_service import EventService, RunEventNotifier
from agentloom.services.run_service import RunService
from tests.integration.test_run_api import delete_task_graph, seed_ready_task


async def test_parallel_node_transitions_have_contiguous_event_sequences() -> None:
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
        store = DatabaseWorkerStore(database.session_factory, notifier)
        reviewer = DeterministicReviewer()
        node_keys = ["research_apple", "research_huawei", "research_xiaomi"]

        async def complete_node(node_key: str) -> None:
            context = await store.load_context(run.id, node_key)
            assert context is not None
            output: dict[str, JsonValue] = {"summary": node_key, "sources": []}
            usage: JsonObject = {
                "model": "mock/test",
                "input_tokens": 1,
                "output_tokens": 1,
            }
            assert await store.start_attempt(context, build_worker_messages(context))
            assert await store.mark_reviewing(context, output, usage)
            review = reviewer.review(output, context.node.output_schema)
            assert review.decision == "accept"
            assert await store.accept(context, output, review)

        await asyncio.gather(*(complete_node(node_key) for node_key in node_keys))

        async with database.session_factory() as session:
            events = await EventService(RunEventRepository(session)).list_after(run.id, 0)
            snapshot = await RunRepository(session).get_snapshot(run.id)

        assert [event.sequence for event in events] == list(range(1, 13))
        assert len({event.sequence for event in events}) == 12
        assert [event.type for event in events].count("node.started") == 3
        assert [event.type for event in events].count("llm.usage_recorded") == 3
        assert [event.type for event in events].count("node.reviewed") == 3
        assert [event.type for event in events].count("node.completed") == 3
        assert {event.node_key for event in events} == set(node_keys)
        assert snapshot is not None
        assert all(
            node_run.status is NodeRunStatus.COMPLETED
            for node_run in snapshot.node_runs
            if node_run.node_key in node_keys
        )
    finally:
        await delete_task_graph(database, task.id)
        await database.dispose()
