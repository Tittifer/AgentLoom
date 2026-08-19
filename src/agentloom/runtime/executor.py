"""Deterministic node executor used before LLM integration."""

import asyncio
from collections.abc import Collection, Mapping
from typing import Protocol
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentloom.db.base import JsonObject
from agentloom.repositories.events import RunEventRepository
from agentloom.repositories.runs import RunRepository
from agentloom.services.event_service import EventService, RunEventNotifier


class NodeExecutionStore(Protocol):
    """Committed state transitions required by a node executor."""

    async def mark_running(self, run_id: UUID, node_key: str) -> bool: ...

    async def mark_reviewing(self, run_id: UUID, node_key: str) -> bool: ...

    async def complete(
        self,
        run_id: UUID,
        node_key: str,
        output: JsonObject,
    ) -> bool: ...

    async def fail(
        self,
        run_id: UUID,
        node_key: str,
        error: JsonObject,
    ) -> bool: ...


class DatabaseNodeExecutionStore:
    """Persist every executor transition in its own database transaction."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        event_notifier: RunEventNotifier,
    ) -> None:
        self._session_factory = session_factory
        self._event_notifier = event_notifier

    async def mark_running(self, run_id: UUID, node_key: str) -> bool:
        transitioned = False
        async with self._session_factory.begin() as session:
            transitioned = await RunRepository(session).mark_node_running(run_id, node_key)
            if transitioned:
                await EventService(RunEventRepository(session)).append(
                    run_id,
                    "node.started",
                    node_key=node_key,
                    payload={"status": "running"},
                )
        if transitioned:
            await self._event_notifier.notify(run_id)
        return transitioned

    async def mark_reviewing(self, run_id: UUID, node_key: str) -> bool:
        transitioned = False
        async with self._session_factory.begin() as session:
            transitioned = await RunRepository(session).mark_node_reviewing(run_id, node_key)
            if transitioned:
                await EventService(RunEventRepository(session)).append(
                    run_id,
                    "node.reviewed",
                    node_key=node_key,
                    payload={"status": "reviewing"},
                )
        if transitioned:
            await self._event_notifier.notify(run_id)
        return transitioned

    async def complete(
        self,
        run_id: UUID,
        node_key: str,
        output: JsonObject,
    ) -> bool:
        transitioned = False
        async with self._session_factory.begin() as session:
            transitioned = await RunRepository(session).complete_node(run_id, node_key, output)
            if transitioned:
                await EventService(RunEventRepository(session)).append(
                    run_id,
                    "node.completed",
                    node_key=node_key,
                    payload={"status": "completed"},
                )
        if transitioned:
            await self._event_notifier.notify(run_id)
        return transitioned

    async def fail(
        self,
        run_id: UUID,
        node_key: str,
        error: JsonObject,
    ) -> bool:
        transitioned = False
        async with self._session_factory.begin() as session:
            transitioned = await RunRepository(session).fail_node(run_id, node_key, error)
            if transitioned:
                payload: JsonObject = {"status": "failed"}
                if "code" in error:
                    payload["code"] = error["code"]
                await EventService(RunEventRepository(session)).append(
                    run_id,
                    "node.failed",
                    node_key=node_key,
                    payload=payload,
                )
        if transitioned:
            await self._event_notifier.notify(run_id)
        return transitioned


class MockNodeExecutor:
    """Complete nodes with deterministic delays and fixed JSON outputs."""

    def __init__(
        self,
        store: NodeExecutionStore,
        delays: Mapping[str, float] | None = None,
        fail_node_keys: Collection[str] = (),
    ) -> None:
        self._store = store
        self._delays = dict(delays or {})
        self._fail_node_keys = set(fail_node_keys)
        self._logger = structlog.get_logger(__name__)

    async def execute(self, run_id: UUID, node_key: str) -> None:
        """Execute one node without propagating node-level failures."""

        try:
            if not await self._store.mark_running(run_id, node_key):
                return
            await asyncio.sleep(self._delay_for(node_key))
            if node_key in self._fail_node_keys:
                raise RuntimeError(f"Configured mock failure for {node_key}")
            if not await self._store.mark_reviewing(run_id, node_key):
                return
            await self._store.complete(run_id, node_key, self._output_for(node_key))
        except Exception as error:
            self._logger.exception(
                "mock_node_execution_failed",
                run_id=str(run_id),
                node_key=node_key,
            )
            try:
                await self._store.fail(
                    run_id,
                    node_key,
                    {
                        "code": "MOCK_EXECUTION_FAILED",
                        "message": str(error),
                    },
                )
            except Exception:
                self._logger.exception(
                    "mock_node_failure_persistence_failed",
                    run_id=str(run_id),
                    node_key=node_key,
                )

    def _delay_for(self, node_key: str) -> float:
        return self._delays.get(node_key, (sum(map(ord, node_key)) % 3 + 1) * 0.01)

    @staticmethod
    def _output_for(node_key: str) -> JsonObject:
        return {
            "node_key": node_key,
            "result": f"Mock output for {node_key}",
        }


__all__ = ["DatabaseNodeExecutionStore", "MockNodeExecutor", "NodeExecutionStore"]
