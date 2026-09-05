"""File-backed Queen identity profiles shared by isolated sessions."""

from __future__ import annotations

import asyncio
import hashlib
import re
from pathlib import Path
from uuid import UUID

from agentloom.colony.schemas import QueenCreate, QueenRead, QueenRuntimeConfig
from agentloom.llm.model_routing import infer_model_protocol
from agentloom.storage.base import atomic_write_json, atomic_write_yaml, read_yaml, utc_now

QUEEN_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,99}$")


class LocalQueenStore:
    """Persist Queen identity only; conversation state remains session-scoped."""

    def __init__(self, root: Path) -> None:
        self._queens = root.expanduser().resolve() / "queens"
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        await asyncio.to_thread(self._queens.mkdir, parents=True, exist_ok=True)

    async def create(self, payload: QueenCreate) -> QueenRead:
        async with self._lock:
            queen_id = _queen_id_from_name(payload.name)
            existing = await asyncio.to_thread(self._get_sync, queen_id)
            if existing is not None:
                raise FileExistsError(queen_id)
            now = utc_now()
            config = QueenRuntimeConfig(
                id=queen_id,
                name=payload.name,
                description=payload.description,
                system_prompt=payload.system_prompt,
                model=payload.model,
                base_url=payload.base_url,
                settings=payload.settings,
                protocol=infer_model_protocol(payload.model),
                api_key=payload.api_key,
                created_at=now,
                updated_at=now,
            )
            await asyncio.to_thread(self._write_sync, config)
            return _public_queen(config)

    async def list(self) -> list[QueenRead]:
        return await asyncio.to_thread(self._list_sync)

    async def get(self, queen_id: str) -> QueenRead | None:
        return await asyncio.to_thread(self._get_sync, queen_id)

    async def get_runtime_config(self, queen_id: str) -> QueenRuntimeConfig | None:
        return await asyncio.to_thread(self._get_runtime_config_sync, queen_id)

    async def add_session_reference(
        self,
        queen_id: str,
        session_id: UUID,
        colony_id: UUID,
    ) -> None:
        async with self._lock:
            if await asyncio.to_thread(self._get_sync, queen_id) is None:
                raise KeyError(queen_id)
            path = self._queens / queen_id / "sessions" / f"{session_id}.json"
            await asyncio.to_thread(
                atomic_write_json,
                path,
                {"session_id": str(session_id), "colony_id": str(colony_id)},
            )

    async def remove_session_reference(self, queen_id: str, session_id: UUID) -> None:
        path = self._queens / queen_id / "sessions" / f"{session_id}.json"
        async with self._lock:
            await asyncio.to_thread(path.unlink, missing_ok=True)

    def _list_sync(self) -> list[QueenRead]:
        if not self._queens.exists():
            return []
        values = [
            _public_queen(QueenRuntimeConfig.model_validate(read_yaml(path)))
            for path in self._queens.glob("*/profile.yaml")
        ]
        return sorted(values, key=lambda item: item.created_at)

    def _get_sync(self, queen_id: str) -> QueenRead | None:
        if QUEEN_ID_PATTERN.fullmatch(queen_id) is None:
            return None
        config = self._get_runtime_config_sync(queen_id)
        return _public_queen(config) if config is not None else None

    def _get_runtime_config_sync(self, queen_id: str) -> QueenRuntimeConfig | None:
        if QUEEN_ID_PATTERN.fullmatch(queen_id) is None:
            return None
        path = self._queens / queen_id / "profile.yaml"
        return QueenRuntimeConfig.model_validate(read_yaml(path)) if path.is_file() else None

    def _write_sync(self, queen: QueenRuntimeConfig) -> None:
        base = self._queens / queen.id
        (base / "sessions").mkdir(parents=True, exist_ok=True)
        value = queen.model_dump(mode="json", exclude={"api_key"})
        value["api_key"] = queen.api_key
        atomic_write_yaml(base / "profile.yaml", value)


def _queen_id_from_name(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:80]
    if not slug or slug == "queen":
        slug = f"custom_{hashlib.sha256(name.encode('utf-8')).hexdigest()[:10]}"
    return slug if slug.startswith("queen_") else f"queen_{slug}"


def _public_queen(config: QueenRuntimeConfig) -> QueenRead:
    return QueenRead.model_validate(config.model_dump(mode="python", exclude={"api_key"}))


__all__ = ["LocalQueenStore"]
