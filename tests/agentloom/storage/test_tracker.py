"""Tests for the per-Colony SQLite Tracker."""

import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest

from agentloom.colony.schemas import TrackerUpsert
from agentloom.storage.tracker import SQLiteTrackerStore, TrackerVersionConflictError


async def test_tracker_is_wal_backed_and_supports_optimistic_updates(tmp_path: Path) -> None:
    path = tmp_path / "tracker" / "tracker.db"
    colony_id = uuid4()
    session_id = uuid4()
    store = SQLiteTrackerStore()

    first = await store.upsert(
        path,
        colony_id,
        session_id,
        TrackerUpsert(namespace="research", entry_key="A", data={"score": 1}),
    )
    second = await store.upsert(
        path,
        colony_id,
        session_id,
        TrackerUpsert(
            namespace="research",
            entry_key="A",
            status="done",
            data={"score": 2},
            expected_version=first.version,
        ),
    )

    with sqlite3.connect(path) as connection:
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()
    assert journal_mode is not None and journal_mode[0] == "wal"
    assert second.version == 2
    assert second.data == {"score": 2}
    assert await store.list(path, colony_id, "research") == [second]

    with pytest.raises(TrackerVersionConflictError):
        await store.upsert(
            path,
            colony_id,
            session_id,
            TrackerUpsert(
                namespace="research",
                entry_key="A",
                expected_version=1,
            ),
        )


async def test_tracker_rejects_expected_version_for_missing_entry(tmp_path: Path) -> None:
    with pytest.raises(TrackerVersionConflictError, match="does not exist"):
        await SQLiteTrackerStore().upsert(
            tmp_path / "tracker.db",
            uuid4(),
            uuid4(),
            TrackerUpsert(namespace="n", entry_key="missing", expected_version=1),
        )
