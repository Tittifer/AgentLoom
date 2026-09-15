"""Pure helpers for deterministic, Tracker-driven Playbook batches."""

from collections.abc import Mapping, Sequence

from pydantic import JsonValue

from agentloom.colony.schemas import JsonObject


class PlaybookContractError(ValueError):
    """Raised when a Playbook query or row violates its declared contract."""


def pending_rows(result: Mapping[str, JsonValue], key_columns: Sequence[str]) -> list[JsonObject]:
    """Validate one Tracker query result and return unique pending rows."""

    if result.get("kind") != "rows":
        raise PlaybookContractError("pending_sql 必须返回 Tracker 行")
    raw_rows = result.get("rows")
    if not isinstance(raw_rows, list):
        raise PlaybookContractError("pending_sql 结果缺少 rows")
    rows: list[JsonObject] = []
    identities: set[str] = set()
    for raw_row in raw_rows:
        if not isinstance(raw_row, dict):
            raise PlaybookContractError("pending_sql 每一行必须是对象")
        row = {str(key): value for key, value in raw_row.items()}
        identity = row_identity(row, key_columns)
        if identity in identities:
            raise PlaybookContractError(f"pending_sql 返回了重复工作单位：{identity}")
        identities.add(identity)
        rows.append(row)
    return rows


def row_identity(row: Mapping[str, JsonValue], key_columns: Sequence[str]) -> str:
    """Build a stable display identity from the declared business key."""

    missing = [column for column in key_columns if column not in row]
    if missing:
        raise PlaybookContractError(
            f"pending_sql 必须返回所有 key_columns，缺少：{', '.join(missing)}"
        )
    return "|".join(f"{column}={row[column]}" for column in key_columns)


def render_task(template: str, row: Mapping[str, JsonValue]) -> str:
    """Render a task template from one pending row without evaluating code."""

    try:
        return template.format_map(_StrictFormatMap(row))
    except KeyError as error:
        raise PlaybookContractError(
            f"task_template 引用了 pending_sql 未返回的列：{error.args[0]}"
        ) from error


class _StrictFormatMap(dict[str, JsonValue]):
    def __missing__(self, key: str) -> JsonValue:
        raise KeyError(key)


__all__ = [
    "PlaybookContractError",
    "pending_rows",
    "render_task",
    "row_identity",
]
