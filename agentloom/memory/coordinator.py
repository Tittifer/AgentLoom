"""Coordinate Queen recall caches and background reflection triggers."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import structlog

from agentloom.agents.loop import LoopContext
from agentloom.llm.base import LLMProvider, LLMResponse
from agentloom.memory.recall import RecallSelector
from agentloom.memory.reflection import ReflectionAgent
from agentloom.memory.store import LocalMemoryStore
from agentloom.storage.colonies import LocalColonyStore

LONG_REFLECT_INTERVAL = 5
SHORT_REFLECT_TURN_INTERVAL = 3
SHORT_REFLECT_COOLDOWN_SECONDS = 300.0
RECALL_SEED_TIMEOUT_SECONDS = 3.0


@dataclass
class ReflectionSessionState:
    completed_turns: int = 0
    short_has_run: bool = False
    last_short_time: float = 0.0


class MemoryCoordinator:
    def __init__(
        self,
        memory_store: LocalMemoryStore,
        colony_store: LocalColonyStore,
        timeout_seconds: float,
    ) -> None:
        self.store = memory_store
        self._colonies = colony_store
        self._recall = RecallSelector(memory_store)
        self._reflection = ReflectionAgent(memory_store, timeout_seconds)
        self._states: dict[UUID, ReflectionSessionState] = {}
        self._active_contexts: dict[UUID, tuple[LoopContext, LLMProvider]] = {}
        self._recall_cache: dict[UUID, str] = {}
        self._recall_seeded: set[UUID] = set()
        self._recall_refreshing: set[UUID] = set()
        self._reflection_lock = asyncio.Lock()
        self._reflection_scheduled = False
        self._tasks: set[asyncio.Task[None]] = set()
        self._accepting = True
        self._logger = structlog.get_logger(__name__)

    async def initialize(self) -> None:
        self._accepting = True
        await self.store.initialize()

    def recalled_memory(self, session_id: UUID) -> str:
        return self._recall_cache.get(session_id, "")

    async def seed_recall(self, session_id: UUID, provider: LLMProvider) -> bool:
        """Bound the first recall attempt so a new Queen turn cannot stall."""

        if not self._accepting or session_id in self._recall_seeded:
            return False
        self._recall_seeded.add(session_id)
        try:
            async with asyncio.timeout(RECALL_SEED_TIMEOUT_SECONDS):
                self._set_recalled_memory(
                    session_id,
                    await self._select_recalled_memory(session_id, provider),
                )
        except TimeoutError:
            self._logger.debug(
                "memory_recall_seed_timeout",
                session_id=str(session_id),
                timeout_seconds=RECALL_SEED_TIMEOUT_SECONDS,
            )
        except Exception as error:
            self._logger.debug(
                "memory_recall_seed_failed",
                session_id=str(session_id),
                error_type=type(error).__name__,
                error=str(error),
            )
        return True

    def schedule_recall(
        self,
        session_id: UUID,
        provider: LLMProvider,
        on_changed: Callable[[str], Awaitable[None]],
    ) -> None:
        """Refresh recall in the background after the cached block is available."""

        if (
            not self._accepting
            or session_id not in self._recall_seeded
            or session_id in self._recall_refreshing
        ):
            return
        self._recall_refreshing.add(session_id)
        self._schedule(self._refresh_recall(session_id, provider, on_changed))

    async def _refresh_recall(
        self,
        session_id: UUID,
        provider: LLMProvider,
        on_changed: Callable[[str], Awaitable[None]],
    ) -> None:
        try:
            previous = self.recalled_memory(session_id)
            refreshed = await self._select_recalled_memory(session_id, provider)
            self._set_recalled_memory(session_id, refreshed)
            if refreshed and refreshed != previous:
                await on_changed(refreshed)
        except Exception as error:
            self._logger.debug(
                "memory_recall_refresh_failed",
                session_id=str(session_id),
                error_type=type(error).__name__,
                error=str(error),
            )
        finally:
            self._recall_refreshing.discard(session_id)

    async def _select_recalled_memory(
        self,
        session_id: UUID,
        provider: LLMProvider,
    ) -> str:
        session = await self._colonies.get_session(session_id)
        if session is None:
            return ""
        queen = await self._colonies.get_queen(session.queen_id)
        llm = await self._colonies.get_user_llm_runtime_config()
        messages = await self._colonies.list_messages(session_id)
        if queen is None or llm is None or messages is None:
            return ""
        query = next(
            (message.content for message in reversed(messages) if message.role == "user"),
            "",
        )
        if not query:
            return ""
        return await self._recall.recall(
            query,
            session.queen_id,
            llm.model,
            provider,
        )

    def _set_recalled_memory(self, session_id: UUID, content: str) -> None:
        if content:
            self._recall_cache[session_id] = content
        else:
            self._recall_cache.pop(session_id, None)

    async def on_turn_completed(
        self,
        context: LoopContext,
        response: LLMResponse,
        provider: LLMProvider,
    ) -> None:
        if not self._accepting or context.session.actor_type != "queen":
            return
        self._active_contexts[context.session.id] = (context, provider)
        state = self._states.setdefault(context.session.id, ReflectionSessionState())
        state.completed_turns += 1
        is_tool_turn = bool(response.tool_calls)
        is_long_interval = state.completed_turns % LONG_REFLECT_INTERVAL == 0
        if is_tool_turn and not is_long_interval:
            return
        if state.short_has_run:
            turn_ok = state.completed_turns % SHORT_REFLECT_TURN_INTERVAL == 0
            cooldown_ok = time.monotonic() - state.last_short_time >= SHORT_REFLECT_COOLDOWN_SECONDS
            if not turn_ok and not cooldown_ok:
                return
        if self._reflection_scheduled or self._reflection_lock.locked():
            return
        state.short_has_run = True
        state.last_short_time = time.monotonic()
        self._reflection_scheduled = True
        self._schedule(self._reflect(context, provider, is_long_interval))

    async def reflect_before_compaction(self, context: LoopContext, provider: LLMProvider) -> None:
        """Capture durable facts before older working context is summarized."""

        if not self._accepting or context.session.actor_type != "queen":
            return
        await self._reflect(context, provider, False)

    async def stop(self) -> None:
        self._accepting = False
        try:
            async with asyncio.timeout(10):
                tasks = tuple(self._tasks)
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
                for context, provider in self._active_contexts.values():
                    await self._reflect(context, provider, False)
        except TimeoutError:
            tasks = tuple(self._tasks)
            self._logger.warning("memory_reflection_shutdown_timeout", task_count=len(tasks))
            if tasks:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
        self._recall_cache.clear()
        self._recall_seeded.clear()
        self._recall_refreshing.clear()
        self._states.clear()
        self._active_contexts.clear()

    async def _reflect(
        self,
        context: LoopContext,
        provider: LLMProvider,
        include_long: bool,
    ) -> None:
        try:
            async with self._reflection_lock:
                messages = await self._colonies.list_messages(context.session.id)
                if messages is None:
                    return
                queen = context.queen or await self._colonies.get_queen(context.session.queen_id)
                if queen is None:
                    return
                changed = await self._reflection.short_reflect(
                    messages,
                    context.session.queen_id,
                    context.model,
                    provider,
                )
                if include_long:
                    changed.extend(
                        await self._reflection.long_reflect(
                            context.session.queen_id,
                            context.model,
                            provider,
                        )
                    )
                self._logger.info(
                    "memory_reflection_completed",
                    session_id=str(context.session.id),
                    changed_files=changed,
                    long_reflection=include_long,
                )
        except Exception as error:
            self._logger.warning(
                "memory_reflection_failed",
                session_id=str(context.session.id),
                error_type=type(error).__name__,
                error=str(error),
            )
        finally:
            self._reflection_scheduled = False

    def _schedule(self, coroutine: Coroutine[Any, Any, None]) -> None:
        if not self._accepting:
            coroutine.close()
            return
        task = asyncio.create_task(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)


__all__ = ["MemoryCoordinator", "ReflectionSessionState"]
