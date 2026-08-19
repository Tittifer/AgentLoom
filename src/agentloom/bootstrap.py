"""Application runtime assembly."""

from agentloom.db.session import DatabaseSessionManager
from agentloom.runtime.executor import DatabaseNodeExecutionStore, MockNodeExecutor
from agentloom.runtime.scheduler import RunScheduler
from agentloom.services.event_service import RunEventNotifier


def create_run_scheduler(
    database: DatabaseSessionManager,
    event_notifier: RunEventNotifier,
) -> RunScheduler:
    """Build the scheduler with deterministic execution and run events."""

    store = DatabaseNodeExecutionStore(database.session_factory, event_notifier)
    executor = MockNodeExecutor(store)
    return RunScheduler(database.session_factory, executor, event_notifier)


__all__ = ["create_run_scheduler"]
