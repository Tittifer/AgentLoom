"""Tests for code-defined application settings."""

from pathlib import Path

from pytest import MonkeyPatch

from agentloom.config import PROJECT_ROOT, Settings


def test_storage_defaults_to_project_root_without_reading_environment(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENTLOOM_HOME", "ignored")
    monkeypatch.setenv("AGENTLOOM_LLM_MODEL", "ignored")

    settings = Settings()

    assert settings.storage_root == PROJECT_ROOT / ".agentloom"
    assert not hasattr(settings, "llm_model")


def test_storage_root_can_be_isolated_by_tests(tmp_path: Path) -> None:
    assert Settings(storage_root=tmp_path).storage_root == tmp_path
