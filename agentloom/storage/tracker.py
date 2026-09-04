"""Per-Colony SQLite Tracker storage."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from uuid import UUID, uuid4

from agentloom.colony.schemas import TrackerEntryRead, TrackerUpsert
from agentloom.storage.base import utc_now

SCHEMA = """
CREATE TABLE IF NOT EXISTS tracker_entries (
    id TEXT PRIMARY KEY,
    namespace TEXT NOT NULL,
    entry_key TEXT NOT NULL,
    status TEXT NOT NULL,
    data_json TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version > 0),
    updated_by_session_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (namespace, entry_key)
);
CREATE TABLE IF NOT EXISTS tracker_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
INSERT OR IGNORE INTO tracker_meta(key, value) VALUES ('schema_version', '1');
"""


class TrackerVersionConflictError(ValueError):
    """Raised when an optimistic Tracker update targets a stale version."""


class SQLiteTrackerStore:
    """Store shared structured state in one SQLite database per Colony."""

    async def initialize(self, path: Path) -> None:
        await asyncio.to_thread(self._initialize, path)

    async def upsert(
        self,
        path: Path,
        colony_id: UUID,
        session_id: UUID,
        payload: TrackerUpsert,
    ) -> TrackerEntryRead:
        return await asyncio.to_thread(
            self._upsert,
            path,
            colony_id,
            session_id,
            payload,
        )

    async def list(
        self,
        path: Path,
        colony_id: UUID,
        namespace: str | None = None,
    ) -> list[TrackerEntryRead]:
        return await asyncio.to_thread(self._list, path, colony_id, namespace)

    @staticmethod
    def _connect(path: Path) -> sqlite3.Connection:
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path, timeout=5.0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @classmethod
    def _initialize(cls, path: Path) -> None:
        connection = cls._connect(path)
        try:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = NORMAL")
            connection.executescript(SCHEMA)
        finally:
            connection.close()

    @classmethod
    def _upsert(
        cls,
        path: Path,
        colony_id: UUID,
        session_id: UUID,
        payload: TrackerUpsert,
    ) -> TrackerEntryRead:
        cls._initialize(path)
        connection = cls._connect(path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM tracker_entries WHERE namespace = ? AND entry_key = ?",
                (payload.namespace, payload.entry_key),
            ).fetchone()
            now = utc_now().isoformat()
            if row is None:
                if payload.expected_version is not None:
                    raise TrackerVersionConflictError("Tracker entry does not exist")
                entry_id = str(uuid4())
                connection.execute(
                    """
                    INSERT INTO tracker_entries(
                        id, namespace, entry_key, status, data_json, version,
                        updated_by_session_id, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)
                    """,
                    (
                        entry_id,
                        payload.namespace,
                        payload.entry_key,
                        payload.status,
                        json.dumps(payload.data, ensure_ascii=False, separators=(",", ":")),
                        str(session_id),
                        now,
                        now,
                    ),
                )
            else:
                current_version = int(row["version"])
                if (
                    payload.expected_version is not None
                    and current_version != payload.expected_version
                ):
                    raise TrackerVersionConflictError(
                        f"Expected tracker version {payload.expected_version}, "
                        f"found {current_version}"
                    )
                entry_id = str(row["id"])
                connection.execute(
                    """
                    UPDATE tracker_entries
                    SET status = ?, data_json = ?, version = ?,
                        updated_by_session_id = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        payload.status,
                        json.dumps(payload.data, ensure_ascii=False, separators=(",", ":")),
                        current_version + 1,
                        str(session_id),
                        now,
                        entry_id,
                    ),
                )
            saved = connection.execute(
                "SELECT * FROM tracker_entries WHERE id = ?", (entry_id,)
            ).fetchone()
            if saved is None:
                raise RuntimeError("Tracker update did not produce a row")
            connection.commit()
            return cls._row_to_read(saved, colony_id)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @classmethod
    def _list(
        cls,
        path: Path,
        colony_id: UUID,
        namespace: str | None,
    ) -> list[TrackerEntryRead]:
        cls._initialize(path)
        connection = cls._connect(path)
        try:
            if namespace is None:
                rows = connection.execute(
                    "SELECT * FROM tracker_entries ORDER BY namespace, entry_key"
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT * FROM tracker_entries
                    WHERE namespace = ? ORDER BY namespace, entry_key
                    """,
                    (namespace,),
                ).fetchall()
        finally:
            connection.close()
        return [cls._row_to_read(row, colony_id) for row in rows]

    @staticmethod
    def _row_to_read(row: sqlite3.Row, colony_id: UUID) -> TrackerEntryRead:
        return TrackerEntryRead.model_validate(
            {
                "id": row["id"],
                "colony_id": colony_id,
                "namespace": row["namespace"],
                "entry_key": row["entry_key"],
                "status": row["status"],
                "data": json.loads(row["data_json"]),
                "version": row["version"],
                "updated_by_session_id": row["updated_by_session_id"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
        )


__all__ = ["SQLiteTrackerStore", "TrackerVersionConflictError"]
