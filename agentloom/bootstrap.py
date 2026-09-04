"""Application runtime assembly."""

from agentloom.colony.notifier import ColonyEventNotifier
from agentloom.colony.runtime import ColonyRuntime
from agentloom.config import Settings
from agentloom.llm.base import LLMProvider
from agentloom.llm.litellm_provider import LiteLLMProvider
from agentloom.llm.mock import SchemaMockLLMProvider
from agentloom.storage import LocalColonyStore
from agentloom.tools.registry import create_builtin_tool_registry


def create_colony_runtime(
    storage: LocalColonyStore,
    event_notifier: ColonyEventNotifier,
    settings: Settings,
) -> ColonyRuntime:
    """Build the persistent Queen/Worker runtime."""

    return ColonyRuntime(
        storage,
        create_llm_provider(settings),
        event_notifier,
        settings,
        create_builtin_tool_registry(),
    )


def create_llm_provider(settings: Settings) -> LLMProvider:
    """Select mock or LiteLLM without changing Colony runtime code."""

    if settings.llm_provider == "mock":
        return SchemaMockLLMProvider(settings.llm_model)
    return LiteLLMProvider(response_format=settings.llm_response_format)


__all__ = ["create_colony_runtime", "create_llm_provider"]
