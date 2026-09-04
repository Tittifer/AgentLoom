"""Tests for atomic local file primitives."""

from pathlib import Path

from agentloom.storage.base import (
    append_json_line,
    atomic_write_json,
    read_json,
    read_json_lines,
)


def test_json_documents_are_replaced_and_jsonl_is_appended(tmp_path: Path) -> None:
    document = tmp_path / "nested" / "state.json"
    atomic_write_json(document, {"version": 1})
    atomic_write_json(document, {"version": 2, "text": "中文"})

    events = tmp_path / "events.jsonl"
    append_json_line(events, {"sequence": 1})
    append_json_line(events, {"sequence": 2})

    assert read_json(document) == {"version": 2, "text": "中文"}
    assert read_json_lines(events) == [{"sequence": 1}, {"sequence": 2}]
    assert list(document.parent.glob("*.tmp")) == []


def test_missing_jsonl_is_an_empty_log(tmp_path: Path) -> None:
    assert read_json_lines(tmp_path / "missing.jsonl") == []
