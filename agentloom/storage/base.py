"""Shared filesystem primitives for local persistence."""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import yaml

ATOMIC_REPLACE_ATTEMPTS = 5
ATOMIC_REPLACE_RETRY_SECONDS = 0.01


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""

    return datetime.now(UTC)


def read_json(path: Path) -> dict[str, Any]:
    """Read one required JSON object."""

    with path.open(encoding="utf-8") as handle:
        value = cast(object, json.load(handle))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return cast(dict[str, Any], value)


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    """Durably replace a JSON document without exposing partial content."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        for attempt in range(ATOMIC_REPLACE_ATTEMPTS):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt == ATOMIC_REPLACE_ATTEMPTS - 1:
                    raise
                time.sleep(ATOMIC_REPLACE_RETRY_SECONDS * (2**attempt))
    finally:
        temporary.unlink(missing_ok=True)


def read_yaml(path: Path) -> dict[str, Any]:
    """Read one required YAML mapping."""

    with path.open(encoding="utf-8") as handle:
        value = cast(object, yaml.safe_load(handle))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a YAML mapping in {path}")
    return cast(dict[str, Any], value)


def atomic_write_yaml(path: Path, value: dict[str, Any]) -> None:
    """Durably replace a YAML document without exposing partial content."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            yaml.safe_dump(value, handle, allow_unicode=True, sort_keys=False)
            handle.flush()
            os.fsync(handle.fileno())
        for attempt in range(ATOMIC_REPLACE_ATTEMPTS):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt == ATOMIC_REPLACE_ATTEMPTS - 1:
                    raise
                time.sleep(ATOMIC_REPLACE_RETRY_SECONDS * (2**attempt))
    finally:
        temporary.unlink(missing_ok=True)


def read_json_lines(path: Path) -> list[dict[str, Any]]:
    """Read an append-only JSONL document."""

    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            value = cast(object, json.loads(line))
            if not isinstance(value, dict):
                raise ValueError(f"Expected a JSON object in {path}:{line_number}")
            records.append(cast(dict[str, Any], value))
    return records


def append_json_line(path: Path, value: dict[str, Any]) -> None:
    """Durably append one compact JSON record."""

    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n"
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())


__all__ = [
    "append_json_line",
    "atomic_write_json",
    "atomic_write_yaml",
    "read_json",
    "read_json_lines",
    "read_yaml",
    "utc_now",
]
