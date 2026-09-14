"""Memory orchestration trigger tests."""

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID

from pytest import MonkeyPatch

from agentloom.agents.loop import LoopContext
from agentloom.colony.schemas import QueenCreate
from agentloom.llm.base import LLMMessage, LLMRequest, LLMResponse, LLMStreamChunk
from agentloom.llm.mock import ScriptedMockLLMProvider
from agentloom.memory.coordinator import MemoryCoordinator
from agentloom.memory.store import LocalMemoryStore
from agentloom.storage import LocalColonyStore
from agentloom.user_settings import UserSettingsUpdate


class HangingRecallProvider:
    def __init__(self) -> None:
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMStreamChunk]:
        del request
        if False:
            yield LLMStreamChunk()


async def _create_recall_coordinator(tmp_path: Path) -> tuple[MemoryCoordinator, UUID]:
    colonies = LocalColonyStore(tmp_path)
    await colonies.initialize()
    await colonies.update_user_settings(
        UserSettingsUpdate(
            model="mock/test",
            base_url="http://localhost:8001",
            api_key="test-key",
        )
    )
    queen = await colonies.create_queen(QueenCreate(name="Recall Test"))
    _, session = await colonies.create("Recall", "", queen.id, {})
    await colonies.append_message(
        session.id,
        LLMMessage(role="user", content="Build a FastAPI service"),
    )
    memory_store = LocalMemoryStore(tmp_path)
    coordinator = MemoryCoordinator(memory_store, colonies, 1)
    await coordinator.initialize()
    await memory_store.write(
        "global",
        "stack.md",
        "---\nname: Stack\ndescription: Backend stack\ntype: preference\n---\n\nFastAPI\n",
    )
    await memory_store.write(
        "global",
        "style.md",
        "---\nname: Style\ndescription: Answer style\ntype: preference\n---\n\nConcise\n",
    )
    return coordinator, session.id


async def test_first_queen_text_turn_schedules_short_reflection(tmp_path: Path) -> None:
    colonies = LocalColonyStore(tmp_path)
    await colonies.initialize()
    await colonies.update_user_settings(
        UserSettingsUpdate(
            model="mock/test",
            base_url="http://localhost:8001",
            api_key="test-key",
        )
    )
    queen = await colonies.create_queen(QueenCreate(name="Memory Test"))
    colony, session = await colonies.create("测试", "", queen.id, {})
    await colonies.append_message(session.id, LLMMessage(role="user", content="我偏好 FastAPI"))
    await colonies.append_message(session.id, LLMMessage(role="assistant", content="已了解"))
    messages = await colonies.list_messages(session.id)
    assert messages is not None
    execution = await colonies.get_execution(session.id)
    assert execution is not None
    context = LoopContext(session=execution, colony=colony, messages=[], model="mock/test")
    provider = ScriptedMockLLMProvider(
        [
            LLMResponse(content="无需保存", model="mock/test"),
            LLMResponse(content="关闭前无需补充", model="mock/test"),
        ]
    )
    coordinator = MemoryCoordinator(LocalMemoryStore(tmp_path), colonies, 1)
    await coordinator.initialize()

    await coordinator.on_turn_completed(
        context,
        LLMResponse(content="已了解", model="mock/test"),
        provider,
    )
    await asyncio.sleep(0)
    await coordinator.stop()

    assert len(provider.requests) == 2


async def test_recall_is_seeded_once_then_refreshed_in_background(tmp_path: Path) -> None:
    coordinator, session_id = await _create_recall_coordinator(tmp_path)
    provider = ScriptedMockLLMProvider(
        [
            LLMResponse(
                content='{"selected_memories":["stack.md"]}',
                model="mock/test",
            ),
            LLMResponse(
                content='{"selected_memories":["style.md"]}',
                model="mock/test",
            ),
        ]
    )

    assert await coordinator.seed_recall(session_id, provider) is True
    assert await coordinator.seed_recall(session_id, provider) is False
    assert "FastAPI" in coordinator.recalled_memory(session_id)

    refreshed = asyncio.Event()
    injected: list[str] = []

    async def on_changed(content: str) -> None:
        injected.append(content)
        refreshed.set()

    coordinator.schedule_recall(session_id, provider, on_changed)
    await asyncio.wait_for(refreshed.wait(), 1)

    assert len(provider.requests) == 2
    assert len(injected) == 1
    assert "Concise" in injected[0]
    assert "FastAPI" not in coordinator.recalled_memory(session_id)
    await coordinator.stop()


async def test_initial_recall_timeout_does_not_block_the_queen_turn(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "agentloom.memory.coordinator.RECALL_SEED_TIMEOUT_SECONDS",
        0.2,
    )
    coordinator, session_id = await _create_recall_coordinator(tmp_path)
    provider = HangingRecallProvider()

    assert await coordinator.seed_recall(session_id, provider) is True

    assert len(provider.requests) == 1
    assert coordinator.recalled_memory(session_id) == ""
    await coordinator.stop()
