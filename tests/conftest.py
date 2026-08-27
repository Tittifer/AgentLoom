"""Global test isolation from developer machine model credentials."""

import pytest


@pytest.fixture(autouse=True)
def use_offline_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep every pytest test deterministic even when local `.env` uses LiteLLM."""

    monkeypatch.setenv("AGENTLOOM_LLM_PROVIDER", "mock")
    monkeypatch.setenv("AGENTLOOM_LLM_MODEL", "mock/schema")
    monkeypatch.setenv("AGENTLOOM_LLM_RESPONSE_FORMAT", "json_schema")
