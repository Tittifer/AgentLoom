"""Hive-style per-Colony SQLite data workspace."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import sqlite3
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

from pydantic import JsonValue

from agentloom.colony.schemas import (
    JsonObject,
    TrackerChangeRead,
    TrackerChangesRead,
    TrackerColumnRead,
    TrackerRowsRead,
    TrackerTableRead,
    TrackerUpsert,
)
from agentloom.storage.base import utc_now

_INTERNAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS _tracker_registry (
    table_name TEXT PRIMARY KEY,
    write_columns_json TEXT NOT NULL,
    key_columns_json TEXT NOT NULL,
    registered_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS _tracker_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS _tracker_changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    table_name TEXT NOT NULL,
    primary_key_json TEXT NOT NULL,
    operation TEXT NOT NULL CHECK (operation IN ('insert', 'update', 'delete')),
    changed_at TEXT NOT NULL
);
INSERT OR REPLACE INTO _tracker_meta(key, value) VALUES ('schema_version', '2');
"""

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_FORBIDDEN_SQL = re.compile(
    r"\b(?:ATTACH|DETACH|PRAGMA|VACUUM|REINDEX)\b|load_extension\s*\(",
    re.IGNORECASE,
)
_READ_SQL = re.compile(r"^\s*(?:SELECT|EXPLAIN|WITH)\b", re.IGNORECASE)
_PROTECTED_REFERENCE = re.compile(
    r"\b(?:TABLE|INTO|UPDATE|FROM|JOIN)\s+"
    r"(?:IF\s+(?:NOT\s+)?EXISTS\s+)?[\"`\[]?_",
    re.IGNORECASE,
)


class TrackerPermissionError(ValueError):
    """Raised when a Tracker statement exceeds the caller's permissions."""


class SQLiteTrackerStore:
    """Expose one isolated SQLite workspace for each Colony."""

    async def initialize(self, path: Path) -> None:
        await asyncio.to_thread(self._initialize, path)

    async def execute_sql(self, path: Path, sql: str, row_cap: int = 1_000) -> JsonObject:
        return await asyncio.to_thread(self._execute_sql, path, sql, row_cap)

    async def register_writable(
        self,
        path: Path,
        table: str,
        write_columns: list[str],
        key_columns: list[str],
    ) -> JsonObject:
        return await asyncio.to_thread(
            self._register_writable, path, table, write_columns, key_columns
        )

    async def upsert(self, path: Path, payload: TrackerUpsert) -> JsonObject:
        return await asyncio.to_thread(self._upsert, path, payload)

    async def query(self, path: Path, sql: str, row_cap: int = 1_000) -> JsonObject:
        return await asyncio.to_thread(self._query, path, sql, row_cap)

    async def list_tables(self, path: Path) -> list[TrackerTableRead]:
        return await asyncio.to_thread(self._list_tables, path)

    async def list_rows(
        self,
        path: Path,
        table: str,
        *,
        limit: int = 100,
        offset: int = 0,
        order_by: str | None = None,
        order_dir: str = "asc",
    ) -> TrackerRowsRead:
        return await asyncio.to_thread(
            self._list_rows, path, table, limit, offset, order_by, order_dir
        )

    async def list_changes(self, path: Path, since: int = 0) -> TrackerChangesRead:
        return await asyncio.to_thread(self._list_changes, path, since)

    @staticmethod
    def _connect(path: Path) -> sqlite3.Connection:
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path, timeout=5.0)
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
            connection.executescript(_INTERNAL_SCHEMA)
            connection.commit()
        finally:
            connection.close()

    @classmethod
    def _execute_sql(cls, path: Path, sql: str, row_cap: int) -> JsonObject:
        statements = cls._split_statements(sql)
        if not statements:
            raise ValueError("SQL 不能为空")
        for statement in statements:
            cls._validate_sql(statement, read_only=False)
        cls._initialize(path)
        connection = cls._connect(path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            results = [
                cls._statement_result(connection.execute(statement), row_cap)
                for statement in statements
            ]
            connection.commit()
            if len(results) == 1:
                return results[0]
            return cast(
                JsonObject,
                {
                    "kind": "batch",
                    "statement_count": len(results),
                    "results": results,
                },
            )
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @classmethod
    def _query(cls, path: Path, sql: str, row_cap: int) -> JsonObject:
        cls._validate_sql(sql, read_only=True)
        cls._initialize(path)
        connection = cls._connect(path)
        try:
            connection.execute("PRAGMA query_only = ON")
            return cls._rows_result(connection.execute(sql), row_cap)
        finally:
            connection.close()

    @classmethod
    def _register_writable(
        cls,
        path: Path,
        table: str,
        write_columns: list[str],
        key_columns: list[str],
    ) -> JsonObject:
        table = cls._user_table_name(table)
        if not write_columns:
            raise ValueError("write_columns 不能为空")
        if not key_columns:
            raise ValueError("key_columns 不能为空")
        write_columns = cls._unique_identifiers(write_columns)
        key_columns = cls._unique_identifiers(key_columns)
        cls._initialize(path)
        connection = cls._connect(path)
        try:
            columns = cls._table_columns(connection, table)
            if not columns:
                raise ValueError(f"Tracker 表不存在：{table}")
            names = {column.name for column in columns}
            unknown = (set(write_columns) | set(key_columns)) - names
            if unknown:
                raise ValueError(f"Tracker 列不存在：{', '.join(sorted(unknown))}")
            allowed = list(dict.fromkeys([*key_columns, *write_columns]))
            index_name = f"_tracker_key_{hashlib.sha1(table.encode()).hexdigest()[:12]}"
            quoted_keys = ", ".join(cls._quote(name) for name in key_columns)
            connection.execute(
                f"CREATE UNIQUE INDEX IF NOT EXISTS {cls._quote(index_name)} "
                f"ON {cls._quote(table)} ({quoted_keys})"
            )
            connection.execute(
                """
                INSERT INTO _tracker_registry(
                    table_name, write_columns_json, key_columns_json, registered_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(table_name) DO UPDATE SET
                    write_columns_json = excluded.write_columns_json,
                    key_columns_json = excluded.key_columns_json,
                    registered_at = excluded.registered_at
                """,
                (
                    table,
                    json.dumps(allowed, ensure_ascii=False),
                    json.dumps(key_columns, ensure_ascii=False),
                    utc_now().isoformat(),
                ),
            )
            cls._install_change_triggers(connection, table, key_columns)
            connection.commit()
            return cast(JsonObject, {
                "table": table,
                "write_columns": allowed,
                "key_columns": key_columns,
            })
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @classmethod
    def _upsert(cls, path: Path, payload: TrackerUpsert) -> JsonObject:
        table = cls._user_table_name(payload.table)
        cls._initialize(path)
        connection = cls._connect(path)
        try:
            registry = connection.execute(
                "SELECT write_columns_json, key_columns_json FROM _tracker_registry "
                "WHERE table_name = ?",
                (table,),
            ).fetchone()
            if registry is None:
                raise TrackerPermissionError(
                    f"表 {table} 未登记为可写；Queen 必须先调用 tracker_register_writable"
                )
            allowed = set(json.loads(registry["write_columns_json"]))
            keys: list[str] = json.loads(registry["key_columns_json"])
            row = dict(payload.row)
            if not row:
                raise ValueError("row 不能为空")
            unknown = set(row) - allowed
            if unknown:
                raise TrackerPermissionError(
                    f"不允许写入列：{', '.join(sorted(unknown))}"
                )
            missing = set(keys) - set(row)
            if missing:
                raise ValueError(f"缺少键列：{', '.join(sorted(missing))}")
            columns = list(row)
            quoted_columns = ", ".join(cls._quote(name) for name in columns)
            placeholders = ", ".join("?" for _ in columns)
            update_columns = [name for name in columns if name not in keys]
            conflict = ", ".join(cls._quote(name) for name in keys)
            action = (
                "DO UPDATE SET "
                + ", ".join(
                    f"{cls._quote(name)} = excluded.{cls._quote(name)}"
                    for name in update_columns
                )
                if update_columns
                else "DO NOTHING"
            )
            connection.execute(
                f"INSERT INTO {cls._quote(table)} ({quoted_columns}) "
                f"VALUES ({placeholders}) ON CONFLICT ({conflict}) {action}",
                tuple(cls._sqlite_value(row[name]) for name in columns),
            )
            where = " AND ".join(f"{cls._quote(name)} = ?" for name in keys)
            saved = connection.execute(
                f"SELECT * FROM {cls._quote(table)} WHERE {where}",
                tuple(cls._sqlite_value(row[name]) for name in keys),
            ).fetchone()
            connection.commit()
            if saved is None:
                raise RuntimeError("Tracker upsert 未返回目标行")
            return {"table": table, "row": cls._row_dict(saved)}
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @classmethod
    def _list_tables(cls, path: Path) -> list[TrackerTableRead]:
        cls._initialize(path)
        connection = cls._connect(path)
        try:
            names = [
                str(row["name"])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' "
                    "AND name NOT LIKE 'sqlite_%' AND substr(name, 1, 1) != '_' ORDER BY name"
                ).fetchall()
            ]
            return [cls._table_overview(connection, name) for name in names]
        finally:
            connection.close()

    @classmethod
    def _list_rows(
        cls,
        path: Path,
        table: str,
        limit: int,
        offset: int,
        order_by: str | None,
        order_dir: str,
    ) -> TrackerRowsRead:
        table = cls._user_table_name(table)
        if limit < 1 or limit > 500:
            raise ValueError("limit 必须在 1 到 500 之间")
        if offset < 0:
            raise ValueError("offset 不能小于 0")
        direction = order_dir.lower()
        if direction not in {"asc", "desc"}:
            raise ValueError("order_dir 必须是 asc 或 desc")
        cls._initialize(path)
        connection = cls._connect(path)
        try:
            columns = cls._table_columns(connection, table)
            if not columns:
                raise KeyError(table)
            column_names = {column.name for column in columns}
            if order_by is not None and order_by not in column_names:
                raise ValueError(f"排序列不存在：{order_by}")
            primary_key = [
                column.name
                for column in sorted(columns, key=lambda item: item.primary_key_position)
                if column.primary_key_position > 0
            ]
            sort_column = order_by or (primary_key[0] if primary_key else None)
            order_clause = (
                f" ORDER BY {cls._quote(sort_column)} {direction.upper()}"
                if sort_column
                else ""
            )
            total = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM {cls._quote(table)}"
                ).fetchone()[0]
            )
            rows = connection.execute(
                f"SELECT * FROM {cls._quote(table)}{order_clause} LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            return TrackerRowsRead(
                table=table,
                columns=columns,
                primary_key=primary_key,
                rows=[cls._row_dict(row) for row in rows],
                total=total,
                limit=limit,
                offset=offset,
            )
        finally:
            connection.close()

    @classmethod
    def _list_changes(cls, path: Path, since: int) -> TrackerChangesRead:
        if since < 0:
            raise ValueError("since 不能小于 0")
        cls._initialize(path)
        connection = cls._connect(path)
        try:
            rows = connection.execute(
                "SELECT * FROM _tracker_changes WHERE id > ? ORDER BY id LIMIT 1000",
                (since,),
            ).fetchall()
            changes = [
                TrackerChangeRead.model_validate(
                    {
                        "id": row["id"],
                        "table": row["table_name"],
                        "primary_key": json.loads(row["primary_key_json"]),
                        "operation": row["operation"],
                        "changed_at": row["changed_at"],
                    }
                )
                for row in rows
            ]
            return TrackerChangesRead(
                changes=changes,
                cursor=int(rows[-1]["id"]) if rows else since,
            )
        finally:
            connection.close()

    @classmethod
    def _table_overview(
        cls, connection: sqlite3.Connection, table: str
    ) -> TrackerTableRead:
        columns = cls._table_columns(connection, table)
        primary_key = [
            column.name
            for column in sorted(columns, key=lambda item: item.primary_key_position)
            if column.primary_key_position > 0
        ]
        count = int(
            connection.execute(f"SELECT COUNT(*) FROM {cls._quote(table)}").fetchone()[0]
        )
        return TrackerTableRead(
            name=table,
            columns=columns,
            row_count=count,
            primary_key=primary_key,
        )

    @classmethod
    def _table_columns(
        cls, connection: sqlite3.Connection, table: str
    ) -> list[TrackerColumnRead]:
        cls._validate_identifier(table)
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        ).fetchone()
        if exists is None:
            return []
        return [
            TrackerColumnRead(
                name=str(row["name"]),
                type=str(row["type"] or ""),
                notnull=bool(row["notnull"]),
                primary_key_position=int(row["pk"]),
                default=row["dflt_value"],
            )
            for row in connection.execute(
                f"PRAGMA table_info({cls._quote(table)})"
            ).fetchall()
        ]

    @classmethod
    def _install_change_triggers(
        cls, connection: sqlite3.Connection, table: str, keys: Sequence[str]
    ) -> None:
        digest = hashlib.sha1(table.encode()).hexdigest()[:12]
        for operation, prefix in (("insert", "NEW"), ("update", "NEW"), ("delete", "OLD")):
            pairs = ", ".join(
                f"'{name}', {prefix}.{cls._quote(name)}" for name in keys
            )
            trigger = cls._quote(f"_tracker_change_{digest}_{operation}")
            connection.execute(f"DROP TRIGGER IF EXISTS {trigger}")
            connection.execute(
                f"CREATE TRIGGER {trigger} AFTER {operation.upper()} ON {cls._quote(table)} "
                "BEGIN "
                "INSERT INTO _tracker_changes(table_name, primary_key_json, operation, changed_at) "
                f"VALUES ('{table}', json_object({pairs}), '{operation}', CURRENT_TIMESTAMP); "
                "END"
            )

    @classmethod
    def _validate_sql(cls, sql: str, *, read_only: bool) -> None:
        if not sql.strip():
            raise ValueError("SQL 不能为空")
        normalized = cls._without_literals_and_comments(sql)
        if _FORBIDDEN_SQL.search(normalized):
            raise TrackerPermissionError("SQL 包含不允许的操作")
        if read_only and not _READ_SQL.match(normalized):
            raise TrackerPermissionError("tracker_query 只允许只读 SQL")
        if re.search(r"\b_tracker_[A-Za-z0-9_]*\b", normalized, re.IGNORECASE):
            raise TrackerPermissionError("不能访问 Tracker 内部表")
        if _PROTECTED_REFERENCE.search(normalized):
            raise TrackerPermissionError("不能访问下划线开头的内部表")

    @staticmethod
    def _without_literals_and_comments(sql: str) -> str:
        value = re.sub(r"--[^\r\n]*", " ", sql)
        value = re.sub(r"/\*.*?\*/", " ", value, flags=re.DOTALL)
        value = re.sub(r"'(?:''|[^'])*'", "''", value)
        return value

    @staticmethod
    def _split_statements(sql: str) -> list[str]:
        statements: list[str] = []
        current: list[str] = []
        quote: str | None = None
        line_comment = False
        block_comment = False
        index = 0
        while index < len(sql):
            char = sql[index]
            following = sql[index + 1] if index + 1 < len(sql) else ""
            if line_comment:
                current.append(char)
                if char in "\r\n":
                    line_comment = False
            elif block_comment:
                current.append(char)
                if char == "*" and following == "/":
                    current.append(following)
                    block_comment = False
                    index += 1
            elif quote is not None:
                current.append(char)
                if quote == "[" and char == "]":
                    quote = None
                elif char == quote:
                    if following == quote:
                        current.append(following)
                        index += 1
                    else:
                        quote = None
            elif char == "-" and following == "-":
                current.extend((char, following))
                line_comment = True
                index += 1
            elif char == "/" and following == "*":
                current.extend((char, following))
                block_comment = True
                index += 1
            elif char in {"'", '"', "`", "["}:
                quote = char
                current.append(char)
            elif char == ";":
                statement = "".join(current).strip()
                if statement:
                    statements.append(statement)
                current = []
            else:
                current.append(char)
            index += 1
        statement = "".join(current).strip()
        if statement:
            statements.append(statement)
        return statements

    @classmethod
    def _user_table_name(cls, value: str) -> str:
        cls._validate_identifier(value)
        if value.startswith("_") or value.lower().startswith("sqlite_"):
            raise TrackerPermissionError("不能访问 Tracker 内部表")
        return value

    @classmethod
    def _unique_identifiers(cls, values: Sequence[str]) -> list[str]:
        result = list(dict.fromkeys(values))
        for value in result:
            cls._validate_identifier(value)
        return result

    @staticmethod
    def _validate_identifier(value: str) -> None:
        if not _IDENTIFIER.fullmatch(value):
            raise ValueError(f"非法 SQLite 标识符：{value}")

    @staticmethod
    def _quote(value: str) -> str:
        return f'"{value.replace(chr(34), chr(34) * 2)}"'

    @staticmethod
    def _sqlite_value(value: JsonValue) -> Any:
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        if isinstance(value, bool):
            return int(value)
        return value

    @classmethod
    def _rows_result(cls, cursor: sqlite3.Cursor, row_cap: int) -> JsonObject:
        cap = min(max(row_cap, 1), 10_000)
        rows = cursor.fetchmany(cap + 1)
        visible = rows[:cap]
        columns = [item[0] for item in cursor.description or []]
        return {
            "kind": "rows",
            "columns": columns,
            "rows": [cls._row_dict(row) for row in visible],
            "rowcount": len(visible),
            "truncated": len(rows) > cap,
        }

    @classmethod
    def _statement_result(cls, cursor: sqlite3.Cursor, row_cap: int) -> JsonObject:
        if cursor.description:
            return cls._rows_result(cursor, row_cap)
        return cast(
            JsonObject,
            {
                "kind": "exec",
                "rowcount": max(cursor.rowcount, 0),
                "last_insert_rowid": cursor.lastrowid,
            },
        )

    @staticmethod
    def _row_dict(row: sqlite3.Row) -> JsonObject:
        return {str(key): row[key] for key in row.keys()}


__all__ = ["SQLiteTrackerStore", "TrackerPermissionError"]
