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
            id="research",
            name="研究 Queen",
            system_prompt="负责研究任务。",
            default_model="mock/schema",
        )
    )

    assert await store.get("research") == queen
    assert await store.list() == [queen]
    assert (tmp_path / "queens" / "research" / "profile.json").is_file()
    assert (tmp_path / "queens" / "research" / "sessions").is_dir()
    with pytest.raises(FileExistsError):
        await store.create(
            QueenCreate(
                id="research",
                name="重复",
                default_model="mock/schema",
            )
        )
