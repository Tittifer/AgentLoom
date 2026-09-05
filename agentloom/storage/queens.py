"""File-backed Queen identity profiles shared by isolated sessions."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from uuid import UUID

from agentloom.colony.schemas import QueenCreate, QueenRead
from agentloom.storage.base import atomic_write_json, read_json, utc_now

QUEEN_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,99}$")


class LocalQueenStore:
    """Persist Queen identity only; conversation state remains session-scoped."""

    def __init__(self, root: Path) -> None:
        self._queens = root.expanduser().resolve() / "queens"
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        await asyncio.to_thread(self._queens.mkdir, parents=True, exist_ok=True)

    async def ensure_default(self, model: str) -> QueenRead:
        existing = await self.get("general")
        if existing is not None:
            return existing
        return await self.create(
            QueenCreate(
                id="general",
                name="AgentLoom",
                description="通用多智能体任务协调 Queen",
                system_prompt="你是 AgentLoom 的通用 Queen，负责理解目标并协调协作任务。",
                default_model=model,
            )
        )

    async def create(self, payload: QueenCreate) -> QueenRead:
        async with self._lock:
            existing = await asyncio.to_thread(self._get_sync, payload.id)
            if existing is not None:
                raise FileExistsError(payload.id)
            now = utc_now()
            queen = QueenRead(**payload.model_dump(), created_at=now, updated_at=now)
            await asyncio.to_thread(self._write_sync, queen)
            return queen

    async def list(self) -> list[QueenRead]:
        return await asyncio.to_thread(self._list_sync)

    async def get(self, queen_id: str) -> QueenRead | None:
        return await asyncio.to_thread(self._get_sync, queen_id)

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
            QueenRead.model_validate(read_json(path))
            for path in self._queens.glob("*/profile.json")
        ]
        return sorted(values, key=lambda item: item.created_at)

    def _get_sync(self, queen_id: str) -> QueenRead | None:
        if QUEEN_ID_PATTERN.fullmatch(queen_id) is None:
            return None
        path = self._queens / queen_id / "profile.json"
        return QueenRead.model_validate(read_json(path)) if path.is_file() else None

    def _write_sync(self, queen: QueenRead) -> None:
        base = self._queens / queen.id
        (base / "sessions").mkdir(parents=True, exist_ok=True)
        atomic_write_json(base / "profile.json", queen.model_dump(mode="json"))


__all__ = ["LocalQueenStore"]
