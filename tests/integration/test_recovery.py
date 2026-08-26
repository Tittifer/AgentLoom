"""PostgreSQL integration tests for restart recovery."""

import asyncio

from agentloom.bootstrap import create_run_scheduler
from agentloom.config import Settings
from agentloom.db.session import DatabaseSessionManager
from agentloom.repositories.events import RunEventRepository
from agentloom.repositories.runs import RunRepository
from agentloom.repositories.tasks import TaskRepository
from agentloom.repositories.workflows import WorkflowRepository
from agentloom.runtime.recovery import recover_active_runs
from agentloom.runtime.states import NodeRunStatus, RunStatus
from agentloom.services.event_service import EventService, RunEventNotifier
from agentloom.services.run_service import RunService
from tests.integration.test_run_api import delete_task_graph, seed_ready_task


async def test_recovery_preserves_completed_nodes_and_resumes_interrupted_run() -> None:
    settings = Settings(environment="test", log_level="WARNING")
    database = DatabaseSessionManager(settings.database_url)
    task = await seed_ready_task(database)
    notifier = RunEventNotifier()

    try:
        async with database.session_factory.begin() as session:
            run = await RunService(
                TaskRepository(session),
                WorkflowRepository(session),
                RunRepository(session),
            ).start_run(task.id)

        async with database.session_factory.begin() as session:
            repository = RunRepository(session)
            assert await repository.mark_run_running(run.id)
            assert await repository.mark_node_running(run.id, "research_apple")
            assert await repository.mark_node_reviewing(
                run.id,
                "research_apple",
                {"summary": "Already complete", "sources": ["source"]},
                {"model": "mock/schema", "input_tokens": 1, "output_tokens": 1},
            )
            assert await repository.complete_node(
                run.id,
                "research_apple",
                {"summary": "Already complete", "sources": ["source"]},
                {"decision": "accept", "score": 1.0, "feedback": "Accepted"},
            )
            assert await repository.mark_node_running(run.id, "research_huawei")

        recovered = await recover_active_runs(database.session_factory, notifier)
        assert recovered == [run.id]

        async with database.session_factory() as session:
            recovered_snapshot = await RunRepository(session).get_snapshot(run.id)
            events = await EventService(RunEventRepository(session)).list_after(run.id, 0)
        assert recovered_snapshot is not None
        statuses = {node.node_key: node.status for node in recovered_snapshot.node_runs}
        assert statuses["research_apple"] is NodeRunStatus.COMPLETED
        assert statuses["research_huawei"] is NodeRunStatus.PENDING
        assert events[-1].type == "run.recovered"
        assert events[-1].payload["reset_nodes"] == 1

        scheduler = create_run_scheduler(database, notifier, settings)
        await scheduler.start()
        try:
            async with asyncio.timeout(10):
                while True:
                    async with database.session_factory() as session:
                        snapshot = await RunRepository(session).get_snapshot(run.id)
                    assert snapshot is not None
                    if snapshot.is_terminal:
                        break
                    await asyncio.sleep(0.05)
        finally:
            await scheduler.stop()

        assert snapshot.run.status is RunStatus.COMPLETED
        apple_attempt = next(
            node for node in snapshot.node_runs if node.node_key == "research_apple"
        )
        assert apple_attempt.attempt == 1
        assert apple_attempt.output == {"summary": "Already complete", "sources": ["source"]}
    finally:
        await delete_task_graph(database, task.id)
        await database.dispose()
