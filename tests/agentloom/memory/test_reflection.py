"""Reflection Agent tests."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from agentloom.colony.schemas import MessageRead
from agentloom.llm.base import LLMResponse, ToolCall
from agentloom.llm.mock import ScriptedMockLLMProvider
from agentloom.memory.reflection import ReflectionAgent
from agentloom.memory.store import LocalMemoryStore


async def test_short_reflection_writes_memory_with_restricted_tool(tmp_path: Path) -> None:
    store = LocalMemoryStore(tmp_path)
    await store.initialize()
    document = "---\nname: 技术偏好\ndescription: 后端框架\ntype: preference\n---\n\nFastAPI\n"
    provider = ScriptedMockLLMProvider(
        [
            LLMResponse(
                model="mock/test",
                tool_calls=[
                    ToolCall(
                        id="write-1",
                        name="write_memory_file",
                        arguments={
                            "scope": "global",
                            "filename": "backend.md",
                            "content": document,
                        },
                    )
                ],
            ),
            LLMResponse(content="已保存", model="mock/test"),
        ]
    )
    messages = [
        _message("user", "我长期使用 FastAPI"),
        _message("tool", "临时工具输出"),
        _message("assistant", "了解"),
    ]

    changed = await ReflectionAgent(store, 1).short_reflect(
        messages, "queen_test", "mock/test", provider
    )

    assert changed == ["global:backend.md"]
    saved = await store.read("global", "backend.md")
    assert saved is not None and saved.content == document
    transcript = provider.requests[0].messages[-1].content
    assert "长期使用 FastAPI" in transcript
    assert "临时工具输出" not in transcript


def _message(role: str, content: str) -> MessageRead:
    return MessageRead(
        id=uuid4(),
        session_id=uuid4(),
        sequence=1,
        role=role,
        content=content,
        tool_call_id=None,
        tool_calls=[],
        metadata={},
        created_at=datetime.now(UTC),
    )
