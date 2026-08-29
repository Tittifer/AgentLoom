"""Test-only ASGI application using the deterministic Colony MockLLM."""

from agentloom.config import Settings
from agentloom.main import create_app

app = create_app(
    Settings(
        environment="test",
        log_level="WARNING",
        llm_provider="mock",
        llm_model="mock/e2e",
    )
)
