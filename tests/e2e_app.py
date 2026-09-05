"""Test-only ASGI application using the deterministic Colony MockLLM."""

from agentloom.config import Settings
from agentloom.llm.mock import SchemaMockLLMProvider
from agentloom.main import create_app

app = create_app(
    Settings(environment="test", log_level="WARNING"),
    SchemaMockLLMProvider("mock/e2e"),
)
