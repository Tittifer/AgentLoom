"""Tests for LLM-selected scoped memory recall."""

from collections.abc import AsyncIterator
from pathlib import Path

from agentloom.llm.base import LLMRequest, LLMRequestError, LLMResponse, LLMStreamChunk
from agentloom.memory.recall import RecallSelector
from agentloom.memory.store import LocalMemoryStore


class RecallProvider:
    def __init__(self) -> None:
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        return LLMResponse(
            content='{"selected_memories":["stack"]}',
            model=request.model,
        )

    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMStreamChunk]:
        del request
        if False:
            yield LLMStreamChunk()


class FailingRecallProvider(RecallProvider):
    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        raise LLMRequestError("response_format is unavailable")


async def test_recall_selects_existing_files_and_pins_profiles(tmp_path: Path) -> None:
    store = LocalMemoryStore(tmp_path)
    await store.initialize()
    await store.write(
        "global",
        "user-profile.md",
        "---\nname: 用户\ndescription: 身份\ntype: profile\n---\n\nPython 工程师\n",
    )
    await store.write(
        "global",
        "stack.md",
        "---\nname: 技术栈\ndescription: 后端偏好\ntype: preference\n---\n\nFastAPI\n",
    )
    provider = RecallProvider()

    block = await RecallSelector(store).recall("后端方案", "queen_test", "mock/test", provider)

    assert "user-profile.md" in block
    assert "stack.md" in block
    assert len(provider.requests) == 1
    assert provider.requests[0].response_format == "json_object"


async def test_recall_does_not_call_llm_when_memory_is_empty(tmp_path: Path) -> None:
    store = LocalMemoryStore(tmp_path)
    await store.initialize()
    provider = RecallProvider()

    assert await RecallSelector(store).recall("问题", "queen_test", "mock/test", provider) == ""
    assert provider.requests == []


async def test_recall_keeps_pinned_memory_when_selection_request_fails(tmp_path: Path) -> None:
    store = LocalMemoryStore(tmp_path)
    await store.initialize()
    await store.write(
        "global",
        "user-profile.md",
        "---\nname: User\ndescription: Profile\ntype: profile\n---\n\nPrefers FastAPI\n",
    )
    provider = FailingRecallProvider()

    block = await RecallSelector(store).recall("backend", "queen_test", "mock/test", provider)

    assert "user-profile.md" in block
    assert len(provider.requests) == 1
    assert provider.requests[0].response_format == "json_object"
