"""Tests for the Hive-style per-Colony SQLite data workspace."""

import sqlite3
from pathlib import Path

import pytest

from agentloom.colony.schemas import TrackerUpsert
from agentloom.storage.tracker import SQLiteTrackerStore, TrackerPermissionError


async def test_queen_creates_table_and_worker_upserts_registered_rows(
    tmp_path: Path,
) -> None:
    path = tmp_path / "tracker" / "tracker.db"
    store = SQLiteTrackerStore()

    await store.execute_sql(
        path,
        """
        CREATE TABLE city_research (
            city TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            summary TEXT,
            facts_json TEXT
        )
        """,
    )
    registered = await store.register_writable(
        path,
        "city_research",
        ["status", "summary", "facts_json"],
        ["city"],
    )
    saved = await store.upsert(
        path,
        TrackerUpsert(
            table="city_research",
            row={
                "city": "杭州",
                "status": "done",
                "summary": "江南山水",
                "facts_json": {"season": "春秋"},
            },
        ),
    )

    with sqlite3.connect(path) as connection:
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()
    assert journal_mode is not None and journal_mode[0] == "wal"
    assert registered["key_columns"] == ["city"]
    assert isinstance(saved["row"], dict)
    assert saved["row"]["city"] == "杭州"

    result = await store.query(
        path,
        "SELECT city, status, facts_json FROM city_research",
    )
    assert result["rows"] == [
        {
            "city": "杭州",
            "status": "done",
            "facts_json": '{"season":"春秋"}',
        }
    ]
    tables = await store.list_tables(path)
    assert [table.name for table in tables] == ["city_research"]
    assert tables[0].row_count == 1
    assert tables[0].primary_key == ["city"]
    page = await store.list_rows(path, "city_research")
    assert page.total == 1
    assert page.rows[0]["summary"] == "江南山水"
    changes = await store.list_changes(path)
    assert len(changes.changes) == 1
    assert changes.changes[0].primary_key == {"city": "杭州"}


async def test_tracker_enforces_registration_columns_and_read_only_query(
    tmp_path: Path,
) -> None:
    path = tmp_path / "tracker.db"
    store = SQLiteTrackerStore()
    await store.execute_sql(path, "CREATE TABLE work (id TEXT PRIMARY KEY, status TEXT)")

    with pytest.raises(TrackerPermissionError, match="未登记"):
        await store.upsert(path, TrackerUpsert(table="work", row={"id": "a"}))

    await store.register_writable(path, "work", ["status"], ["id"])
    with pytest.raises(TrackerPermissionError, match="不允许写入列"):
        await store.upsert(
            path,
            TrackerUpsert(table="work", row={"id": "a", "unknown": "x"}),
        )
    with pytest.raises(TrackerPermissionError, match="只允许只读 SQL"):
        await store.query(path, "DELETE FROM work")
    with pytest.raises(TrackerPermissionError, match="内部表"):
        await store.execute_sql(path, "DELETE FROM _tracker_registry")


async def test_tracker_row_listing_supports_sort_and_pagination(tmp_path: Path) -> None:
    path = tmp_path / "tracker.db"
    store = SQLiteTrackerStore()
    result = await store.execute_sql(
        path,
        """
        CREATE TABLE scores (id INTEGER PRIMARY KEY, score INTEGER);
        INSERT INTO scores(id, score) VALUES (1, 10), (2, 20);
        """,
    )

    page = await store.list_rows(
        path,
        "scores",
        limit=1,
        offset=0,
        order_by="score",
        order_dir="desc",
    )

    assert result["kind"] == "batch"
    assert result["statement_count"] == 2
    assert page.total == 2
    assert page.rows == [{"id": 2, "score": 20}]
