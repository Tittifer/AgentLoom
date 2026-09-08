"""Memory orchestration trigger tests."""

import asyncio
from pathlib import Path

from agentloom.agents.loop import LoopContext
from agentloom.colony.schemas import QueenCreate
from agentloom.llm.base import LLMMessage, LLMResponse
from agentloom.llm.mock import ScriptedMockLLMProvider
from agentloom.memory.coordinator import MemoryCoordinator
from agentloom.memory.store import LocalMemoryStore
from agentloom.storage import LocalColonyStore
from agentloom.user_settings import UserSettingsUpdate


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
    queen = await colonies.create_queen(
        QueenCreate(name="Memory Test")
    )
    colony, session = await colonies.create("测试", "", queen.id, {})
    await colonies.append_message(session.id, LLMMessage(role="user", content="我偏好 FastAPI"))
    await colonies.append_message(session.id, LLMMessage(role="assistant", content="已了解"))
    messages = await colonies.list_messages(session.id)
    assert messages is not None
    context = LoopContext(session=session, colony=colony, messages=[], model="mock/test")
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
