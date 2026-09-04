"""Tests for atomic local file primitives."""

from pathlib import Path

import pytest
from pytest import MonkeyPatch

from agentloom.storage import base as storage_base
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


def test_atomic_json_replace_retries_transient_permission_errors(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    document = tmp_path / "state.json"
    atomic_write_json(document, {"version": 1})
    real_replace = storage_base.os.replace
    attempts = 0

    def flaky_replace(source: Path, target: Path) -> None:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise PermissionError("temporarily locked")
        real_replace(source, target)

    def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(storage_base.os, "replace", flaky_replace)
    monkeypatch.setattr(storage_base.time, "sleep", no_sleep)

    atomic_write_json(document, {"version": 2})

    assert attempts == 3
    assert read_json(document) == {"version": 2}
    assert list(tmp_path.glob("*.tmp")) == []


def test_atomic_json_replace_surfaces_persistent_permission_errors(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    document = tmp_path / "state.json"

    def denied_replace(source: Path, target: Path) -> None:
        del source, target
        raise PermissionError("locked")

    def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(storage_base.os, "replace", denied_replace)
    monkeypatch.setattr(storage_base.time, "sleep", no_sleep)

    with pytest.raises(PermissionError, match="locked"):
        atomic_write_json(document, {"version": 1})

    assert list(tmp_path.glob("*.tmp")) == []
