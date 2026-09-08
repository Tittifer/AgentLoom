"""Tests for global user-managed LLM settings storage."""

from pathlib import Path

from agentloom.storage.settings import LocalUserSettingsStore
from agentloom.user_settings import UserSettingsUpdate


async def test_settings_start_empty_and_store_one_shared_llm_config(tmp_path: Path) -> None:
    store = LocalUserSettingsStore(tmp_path)
    await store.initialize()

    empty = await store.get()
    assert empty.configured is False
    assert (tmp_path / "settings.yaml").read_text(encoding="utf-8") == "{}\n"

    saved = await store.update(
        UserSettingsUpdate(
            model="deepseek-v4-flash",
            base_url="https://api.deepseek.com/",
            api_key="secret-key",
            response_format="json_object",
            max_context_tokens=64_000,
        )
    )

    assert saved.configured is True
    assert saved.protocol == "openai"
    assert saved.api_key_configured is True
    assert "secret-key" not in saved.model_dump_json()
    runtime = await store.get_runtime_config()
    assert runtime is not None and runtime.api_key == "secret-key"
    assert runtime.base_url == "https://api.deepseek.com"
