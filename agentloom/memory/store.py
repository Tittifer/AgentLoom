"""Safe Markdown-file persistence for long-term memory."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import cast

import yaml

from agentloom.memory.schemas import MemoryRead, MemoryScope, MemoryType
from agentloom.storage.base import atomic_write_text

MAX_MEMORY_FILES = 200
MAX_MEMORY_FILE_BYTES = 4096
MEMORY_TYPES = frozenset({"profile", "preference", "environment", "feedback"})


class LocalMemoryStore:
    def __init__(self, storage_root: Path) -> None:
        self.root = storage_root.expanduser().resolve() / "memories"
        self._write_lock = asyncio.Lock()

    async def initialize(self) -> None:
        await asyncio.to_thread((self.root / "global").mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(
            (self.root / "agents" / "queens").mkdir,
            parents=True,
            exist_ok=True,
        )

    async def list(self, scope: MemoryScope, queen_id: str | None = None) -> list[MemoryRead]:
        return await asyncio.to_thread(self._list_sync, scope, queen_id)

    async def list_all(self) -> list[MemoryRead]:
        global_items = await self.list("global")
        queen_items: list[MemoryRead] = []
        queens_root = self.root / "agents" / "queens"
        if queens_root.is_dir():
            for path in sorted(item for item in queens_root.iterdir() if item.is_dir()):
                queen_items.extend(await self.list("queen", path.name))
        return global_items + queen_items

    async def read(
        self,
        scope: MemoryScope,
        filename: str,
        queen_id: str | None = None,
    ) -> MemoryRead | None:
        return await asyncio.to_thread(self._read_sync, scope, filename, queen_id, True)

    async def write(
        self,
        scope: MemoryScope,
        filename: str,
        content: str,
        queen_id: str | None = None,
        *,
        overwrite: bool = True,
    ) -> MemoryRead:
        async with self._write_lock:
            return await asyncio.to_thread(
                self._write_sync,
                scope,
                filename,
                content,
                queen_id,
                overwrite,
            )

    async def delete(
        self,
        scope: MemoryScope,
        filename: str,
        queen_id: str | None = None,
    ) -> bool:
        async with self._write_lock:
            path = self._safe_path(scope, filename, queen_id)
            if not path.is_file():
                return False
            await asyncio.to_thread(path.unlink)
            return True

    def _directory(self, scope: MemoryScope, queen_id: str | None) -> Path:
        if scope == "global":
            return self.root / "global"
        if not queen_id or any(part in queen_id for part in ("/", "\\", "..")):
            raise ValueError("queen scope requires a valid queen_id")
        return self.root / "agents" / "queens" / queen_id

    def _safe_path(self, scope: MemoryScope, filename: str, queen_id: str | None) -> Path:
        if (
            not filename
            or filename != filename.strip()
            or not filename.lower().endswith(".md")
            or any(part in filename for part in ("/", "\\", ".."))
        ):
            raise ValueError("memory filename must be a plain .md filename")
        directory = self._directory(scope, queen_id).resolve()
        target = (directory / filename).resolve()
        if not target.is_relative_to(directory):
            raise ValueError("memory path escapes its scope")
        return target

    def _list_sync(self, scope: MemoryScope, queen_id: str | None) -> list[MemoryRead]:
        directory = self._directory(scope, queen_id)
        if not directory.is_dir():
            return []
        paths = sorted(
            (
                path
                for path in directory.glob("*.md")
                if path.is_file() and not path.name.startswith(".")
            ),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )[:MAX_MEMORY_FILES]
        return [
            cast(MemoryRead, self._read_sync(scope, path.name, queen_id, False)) for path in paths
        ]

    def _read_sync(
        self,
        scope: MemoryScope,
        filename: str,
        queen_id: str | None,
        include_content: bool,
    ) -> MemoryRead | None:
        path = self._safe_path(scope, filename, queen_id)
        if not path.is_file():
            return None
        text = path.read_text(encoding="utf-8")
        metadata = _frontmatter(text)
        relative = path.relative_to(self.root).as_posix()
        return MemoryRead(
            path=relative,
            filename=filename,
            scope=scope,
            queen_id=queen_id if scope == "queen" else None,
            name=_optional_string(metadata.get("name")),
            description=_optional_string(metadata.get("description")),
            type=_memory_type(metadata.get("type")),
            mtime=path.stat().st_mtime,
            content=text if include_content else None,
        )

    def _write_sync(
        self,
        scope: MemoryScope,
        filename: str,
        content: str,
        queen_id: str | None,
        overwrite: bool,
    ) -> MemoryRead:
        encoded = content.encode("utf-8")
        if len(encoded) > MAX_MEMORY_FILE_BYTES:
            raise ValueError(f"memory exceeds {MAX_MEMORY_FILE_BYTES} bytes")
        path = self._safe_path(scope, filename, queen_id)
        if path.exists() and not overwrite:
            raise FileExistsError(filename)
        if not path.exists():
            existing = list(path.parent.glob("*.md")) if path.parent.is_dir() else []
            if len(existing) >= MAX_MEMORY_FILES:
                raise ValueError(f"memory scope already contains {MAX_MEMORY_FILES} files")
        metadata = _frontmatter(content)
        raw_type = metadata.get("type")
        if raw_type is not None and _memory_type(raw_type) is None:
            raise ValueError("invalid memory type")
        normalized = content.rstrip() + "\n"
        atomic_write_text(path, normalized)
        result = self._read_sync(scope, filename, queen_id, True)
        if result is None:
            raise RuntimeError("memory write did not create a readable file")
        return result


def _frontmatter(text: str) -> dict[str, object]:
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end < 0:
        return {}
    value = cast(object, yaml.safe_load(text[4:end]))
    return cast(dict[str, object], value) if isinstance(value, dict) else {}


def _optional_string(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _memory_type(value: object) -> MemoryType | None:
    normalized = _optional_string(value)
    return cast(MemoryType, normalized) if normalized in MEMORY_TYPES else None


__all__ = ["LocalMemoryStore", "MAX_MEMORY_FILES", "MAX_MEMORY_FILE_BYTES"]
