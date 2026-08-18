"""Tests for deterministic mock node execution."""

import asyncio
from uuid import UUID, uuid4

from agentloom.db.base import JsonObject
from agentloom.runtime.executor import MockNodeExecutor


class RecordingStore:
    def __init__(self) -> None:
        self.transitions: list[tuple[str, str]] = []
        self.outputs: dict[str, JsonObject] = {}
        self.errors: dict[str, JsonObject] = {}

    async def mark_running(self, run_id: UUID, node_key: str) -> bool:
        self.transitions.append((node_key, "running"))
        return True

    async def mark_reviewing(self, run_id: UUID, node_key: str) -> bool:
        self.transitions.append((node_key, "reviewing"))
        return True

    async def complete(
        self,
        run_id: UUID,
        node_key: str,
        output: JsonObject,
    ) -> bool:
        self.transitions.append((node_key, "completed"))
        self.outputs[node_key] = output
        return True

    async def fail(
        self,
        run_id: UUID,
        node_key: str,
        error: JsonObject,
    ) -> bool:
        self.transitions.append((node_key, "failed"))
        self.errors[node_key] = error
        return True


async def test_mock_executor_runs_nodes_concurrently_and_returns_fixed_json() -> None:
    store = RecordingStore()
    executor = MockNodeExecutor(
        store,
        delays={"research_a": 0.02, "research_b": 0.01},
    )
    run_id = uuid4()

    await asyncio.gather(
        executor.execute(run_id, "research_a"),
        executor.execute(run_id, "research_b"),
    )

    running_transitions = [
        transition for transition in store.transitions if transition[1] == "running"
    ]
    assert running_transitions == [
        ("research_a", "running"),
        ("research_b", "running"),
    ]
    assert store.outputs["research_a"]["node_key"] == "research_a"
    assert store.outputs["research_b"]["node_key"] == "research_b"


async def test_mock_executor_converts_exceptions_to_failed_state() -> None:
    store = RecordingStore()
    executor = MockNodeExecutor(
        store,
        delays={"broken": 0},
        fail_node_keys={"broken"},
    )

    await executor.execute(uuid4(), "broken")

    assert store.transitions == [("broken", "running"), ("broken", "failed")]
    assert store.errors["broken"]["code"] == "MOCK_EXECUTION_FAILED"
