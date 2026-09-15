"""Tests for deterministic Playbook row contracts."""

import pytest
from pydantic import JsonValue

from agentloom.colony.playbooks import (
    PlaybookContractError,
    pending_rows,
    render_task,
    row_identity,
)


def test_pending_rows_require_unique_declared_keys() -> None:
    result: dict[str, JsonValue] = {
        "kind": "rows",
        "rows": [
            {"fruit_key": "apple", "status": "pending"},
            {"fruit_key": "pear", "status": "pending"},
        ],
    }

    rows = pending_rows(result, ["fruit_key"])

    assert [row_identity(row, ["fruit_key"]) for row in rows] == [
        "fruit_key=apple",
        "fruit_key=pear",
    ]
    assert render_task("调查 {fruit_key}", rows[0]) == "调查 apple"


def test_pending_rows_reject_duplicates_and_missing_template_columns() -> None:
    duplicate: dict[str, JsonValue] = {
        "kind": "rows",
        "rows": [{"id": "a"}, {"id": "a"}],
    }

    with pytest.raises(PlaybookContractError, match="重复工作单位"):
        pending_rows(duplicate, ["id"])
    with pytest.raises(PlaybookContractError, match="未返回的列"):
        render_task("调查 {name}", {"id": "a"})
