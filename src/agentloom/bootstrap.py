"""Application runtime assembly."""

from agentloom.agents.planner import Planner
from agentloom.agents.reviewer import DeterministicReviewer
from agentloom.agents.worker import DatabaseWorkerStore, Worker
from agentloom.config import Settings
from agentloom.db.session import DatabaseSessionManager
from agentloom.llm.base import LLMProvider
from agentloom.llm.litellm_provider import LiteLLMProvider
from agentloom.llm.mock import SchemaMockLLMProvider
from agentloom.runtime.scheduler import RunScheduler
from agentloom.services.event_service import RunEventNotifier
from agentloom.tools.registry import create_builtin_tool_registry


def create_run_scheduler(
    database: DatabaseSessionManager,
    event_notifier: RunEventNotifier,
    settings: Settings,
) -> RunScheduler:
    """Build the scheduler with the configured worker provider and tools."""

    store = DatabaseWorkerStore(database.session_factory, event_notifier)
    worker = Worker(
        store,
        create_llm_provider(settings),
        DeterministicReviewer(),
        create_builtin_tool_registry(),
        model=settings.llm_model,
        max_turns=settings.worker_max_turns,
        timeout_seconds=settings.llm_timeout_seconds,
    )
    return RunScheduler(database.session_factory, worker, event_notifier)


def create_planner(settings: Settings) -> Planner:
    """Build the planner with the same provider selection as the worker runtime."""

    tools = create_builtin_tool_registry()
    return Planner(
        create_llm_provider(settings),
        tools.definitions(),
        model=settings.llm_model,
        timeout_seconds=settings.llm_timeout_seconds,
    )


def create_llm_provider(settings: Settings) -> LLMProvider:
    """Select mock or LiteLLM without changing worker runtime code."""

    if settings.llm_provider == "mock":
        return SchemaMockLLMProvider(settings.llm_model)
    return LiteLLMProvider()


__all__ = ["create_llm_provider", "create_planner", "create_run_scheduler"]
