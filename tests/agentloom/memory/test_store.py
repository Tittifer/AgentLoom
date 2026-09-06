"""Tests for safe Markdown memory persistence."""

from pathlib import Path

import pytest

from agentloom.memory.store import LocalMemoryStore

DOCUMENT = """---
name: 技术偏好
description: 用户偏好的后端技术
type: preference
---

用户偏好 FastAPI。
"""


async def test_store_round_trips_global_and_queen_memories(tmp_path: Path) -> None:
    store = LocalMemoryStore(tmp_path)
    await store.initialize()

    global_item = await store.write("global", "backend.md", DOCUMENT)
    queen_item = await store.write("queen", "style.md", DOCUMENT, "queen_test")

    assert global_item.path == "global/backend.md"
    assert global_item.type == "preference"
    assert queen_item.path == "agents/queens/queen_test/style.md"
    assert [item.filename for item in await store.list("global")] == ["backend.md"]
    assert (await store.read("queen", "style.md", "queen_test")) == queen_item
    assert len(await store.list_all()) == 2


async def test_store_rejects_unsafe_paths_and_oversized_content(tmp_path: Path) -> None:
    store = LocalMemoryStore(tmp_path)
    await store.initialize()

    with pytest.raises(ValueError, match="plain .md"):
        await store.write("global", "../secret.md", DOCUMENT)
    with pytest.raises(ValueError, match="4096 bytes"):
        await store.write("global", "large.md", "中" * 2000)
    with pytest.raises(ValueError, match="valid queen_id"):
        await store.write("queen", "item.md", DOCUMENT, "../other")


async def test_store_create_is_idempotency_safe_and_delete_reports_missing(
    tmp_path: Path,
) -> None:
    store = LocalMemoryStore(tmp_path)
    await store.initialize()
    await store.write("global", "item.md", DOCUMENT, overwrite=False)

    with pytest.raises(FileExistsError):
        await store.write("global", "item.md", DOCUMENT, overwrite=False)
    assert await store.delete("global", "item.md")
    assert not await store.delete("global", "item.md")
