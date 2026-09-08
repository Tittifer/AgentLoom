"""Tests for file-backed Queen identity storage."""

from pathlib import Path

import pytest

from agentloom.colony.schemas import QueenCreate
from agentloom.storage.base import atomic_write_yaml
from agentloom.storage.queens import LocalQueenStore


async def test_queen_profile_is_shared_without_sharing_session_state(tmp_path: Path) -> None:
    store = LocalQueenStore(tmp_path)
    await store.initialize()
    queen = await store.create(
        QueenCreate(
            name="Research",
            system_prompt="负责研究任务。",
        )
    )

    assert queen.id == "queen_research"
    assert await store.get("queen_research") == queen
    assert await store.list() == [queen]
    profile_path = tmp_path / "queens" / "queen_research" / "profile.yaml"
    assert profile_path.is_file()
    assert "api_key" not in profile_path.read_text(encoding="utf-8")
    assert "model:" not in profile_path.read_text(encoding="utf-8")
    assert (tmp_path / "queens" / "queen_research" / "sessions").is_dir()
    with pytest.raises(FileExistsError):
        await store.create(QueenCreate(name="Research"))


async def test_initialize_removes_legacy_llm_fields_from_queen_profiles(tmp_path: Path) -> None:
    profile = tmp_path / "queens" / "queen_legacy" / "profile.yaml"
    atomic_write_yaml(
        profile,
        {
            "id": "queen_legacy",
            "name": "Legacy",
            "description": "",
            "system_prompt": "",
            "model": "gpt-5",
            "protocol": "openai",
            "base_url": "https://api.openai.com",
            "api_key": "must-be-removed",
            "settings": {},
            "created_at": "2026-09-01T00:00:00Z",
            "updated_at": "2026-09-01T00:00:00Z",
        },
    )

    store = LocalQueenStore(tmp_path)
    await store.initialize()

    saved = profile.read_text(encoding="utf-8")
    assert await store.get("queen_legacy") is not None
    assert "model:" not in saved
    assert "api_key" not in saved
