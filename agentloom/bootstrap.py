"""Application runtime assembly."""

from agentloom.colony.notifier import ColonyEventNotifier
from agentloom.colony.runtime import ColonyRuntime
from agentloom.config import Settings
from agentloom.llm.base import LLMProvider
from agentloom.storage import LocalColonyStore
from agentloom.tools.registry import create_builtin_tool_registry


def create_colony_runtime(
    storage: LocalColonyStore,
    event_notifier: ColonyEventNotifier,
    settings: Settings,
    provider: LLMProvider | None = None,
) -> ColonyRuntime:
    """Build the persistent Queen/Worker runtime."""

    return ColonyRuntime(
        storage,
        provider,
        event_notifier,
        settings,
        create_builtin_tool_registry(),
    )

__all__ = ["create_colony_runtime"]
