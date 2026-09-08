"""File-backed global user settings storage."""

from __future__ import annotations

import asyncio
from pathlib import Path

from agentloom.llm.model_routing import infer_model_protocol
from agentloom.storage.base import atomic_write_yaml, read_yaml, utc_now
from agentloom.user_settings import (
    UserLLMRuntimeConfig,
    UserSettingsRead,
    UserSettingsUpdate,
    public_settings,
)


class LocalUserSettingsStore:
    """Persist one local user's shared LLM configuration."""

    def __init__(self, root: Path) -> None:
        self._path = root.expanduser().resolve() / "settings.yaml"
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        async with self._lock:
            await asyncio.to_thread(self._initialize_sync)

    async def get(self) -> UserSettingsRead:
        return public_settings(await self.get_runtime_config())

    async def get_runtime_config(self) -> UserLLMRuntimeConfig | None:
        return await asyncio.to_thread(self._get_runtime_config_sync)

    async def update(self, payload: UserSettingsUpdate) -> UserSettingsRead:
        config = UserLLMRuntimeConfig(
            **payload.model_dump(),
            protocol=infer_model_protocol(payload.model),
            updated_at=utc_now(),
        )
        async with self._lock:
            await asyncio.to_thread(
                atomic_write_yaml,
                self._path,
                config.model_dump(mode="json"),
            )
        return public_settings(config)

    def _initialize_sync(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            atomic_write_yaml(self._path, {})

    def _get_runtime_config_sync(self) -> UserLLMRuntimeConfig | None:
        if not self._path.is_file():
            return None
        value = read_yaml(self._path)
        return UserLLMRuntimeConfig.model_validate(value) if value else None


__all__ = ["LocalUserSettingsStore"]
