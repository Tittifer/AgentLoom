"""Tests for file-backed Queen identity storage."""

from pathlib import Path

import pytest

from agentloom.colony.schemas import QueenCreate
from agentloom.storage.queens import LocalQueenStore


async def test_queen_profile_is_shared_without_sharing_session_state(tmp_path: Path) -> None:
    store = LocalQueenStore(tmp_path)
    await store.initialize()
    queen = await store.create(
        QueenCreate(
            name="Research",
            system_prompt="负责研究任务。",
            model="claude-sonnet-4",
            base_url="https://api.anthropic.com",
            api_key="secret-key",
        )
    )

    assert queen.id == "queen_research"
    assert queen.protocol == "claude"
    assert await store.get("queen_research") == queen
    assert await store.list() == [queen]
    profile_path = tmp_path / "queens" / "queen_research" / "profile.yaml"
    assert profile_path.is_file()
    assert "secret-key" in profile_path.read_text(encoding="utf-8")
    assert (tmp_path / "queens" / "queen_research" / "sessions").is_dir()
    with pytest.raises(FileExistsError):
        await store.create(
            QueenCreate(
                name="Research",
                model="claude-sonnet-4",
                base_url="https://api.anthropic.com",
                api_key="another-key",
            )
        )
