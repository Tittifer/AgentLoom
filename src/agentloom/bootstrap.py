"""Application runtime assembly."""

from agentloom.db.session import DatabaseSessionManager
from agentloom.runtime.executor import DatabaseNodeExecutionStore, MockNodeExecutor
from agentloom.runtime.scheduler import RunScheduler


def create_run_scheduler(database: DatabaseSessionManager) -> RunScheduler:
    """Build the phase-four scheduler with its deterministic executor."""

    store = DatabaseNodeExecutionStore(database.session_factory)
    executor = MockNodeExecutor(store)
    return RunScheduler(database.session_factory, executor)


__all__ = ["create_run_scheduler"]
