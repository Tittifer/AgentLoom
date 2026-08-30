"""Tests for the unified Queen/Worker AgentLoop."""

from datetime import UTC, datetime
from uuid import uuid4

from agentloom.agents.judge import JudgePipeline
from agentloom.agents.loop import AgentLoop, LoopContext, ToolExecutionResult
from agentloom.colony.schemas import ColonyRead, MessageRead, SessionRead
from agentloom.llm.base import LLMMessage, LLMResponse, ToolCall, ToolDefinition
from agentloom.llm.mock import ScriptedMockLLMProvider
from agentloom.runtime.states import ColonyStatus, SessionStatus


def make_context(actor_type: str = "queen") -> LoopContext:
    now = datetime.now(UTC)
    colony_id = uuid4()
    session_id = uuid4()
    return LoopContext(
        colony=ColonyRead(
            id=colony_id,
            name="测试",
            description="",
            status=ColonyStatus.ACTIVE,
            queen_profile="general",
            model="mock/test",
            settings={},
            queen_session_id=session_id,
            created_at=now,
            updated_at=now,
        ),
        session=SessionRead(
            id=session_id,
            colony_id=colony_id,
            parent_session_id=None,
            actor_type=actor_type,  # type: ignore[arg-type]
            status=SessionStatus.QUEUED,
            park_reason=None,
            task={"task": "分析"},
            cursor={},
            budget={"max_turns": 2},
            usage={},
            created_at=now,
            updated_at=now,
            ended_at=None,
        ),
        messages=[LLMMessage(role="user", content="开始")],
    )


class FakeStore:
    def __init__(self, context: LoopContext) -> None:
        self.context = context
        self.messages: list[LLMMessage] = []
        self.checkpoints: list[str] = []
        self.finished = False
        self.failed: Exception | None = None

    async def load(self, session_id):  # type: ignore[no-untyped-def]
        return self.context if session_id == self.context.session.id else None

    async def mark_running(self, context: LoopContext) -> bool:
        return context is self.context

    async def append_message(
        self, context: LoopContext, message: LLMMessage, event_type: str
    ) -> MessageRead:
        del context, event_type
        self.messages.append(message)
        now = datetime.now(UTC)
        return MessageRead(
            id=uuid4(),
            session_id=self.context.session.id,
            sequence=len(self.messages),
            role=message.role,
            content=message.content,
            tool_call_id=message.tool_call_id,
            tool_calls=[call.model_dump(mode="json") for call in message.tool_calls],
            metadata={},
            created_at=now,
        )

    async def checkpoint(
        self, context: LoopContext, iteration: int, phase: str, usage: dict[str, int]
    ) -> None:
        del context, iteration, usage
        self.checkpoints.append(phase)

    async def finish(self, context: LoopContext, content: str, usage: dict[str, int]) -> None:
        del context, content, usage
        self.finished = True

    async def fail(self, context: LoopContext, error: Exception) -> None:
        del context
        self.failed = error


class FakeTools:
    def __init__(self, terminate: bool = False) -> None:
        self.terminate = terminate
        self.calls: list[ToolCall] = []
        self.finalized: list[str] = []

    def definitions(self, actor_type):  # type: ignore[no-untyped-def]
        del actor_type
        return [ToolDefinition(name="lookup", description="查询", parameters={"type": "object"})]

    async def execute(self, context: LoopContext, tool_call: ToolCall) -> ToolExecutionResult:
        del context
        self.calls.append(tool_call)
        if tool_call.argument_error is not None:
            return ToolExecutionResult(
                {
                    "error": {
                        "code": "TOOL_ARGUMENTS_INVALID",
                        "message": tool_call.argument_error,
                    }
                }
            )
        return ToolExecutionResult({"ok": True}, terminate=self.terminate)

    async def finalize_text(self, context: LoopContext, content: str) -> None:
        del context
        self.finalized.append(content)


async def test_agent_loop_finishes_visible_response() -> None:
    context = make_context()
    store = FakeStore(context)
    tools = FakeTools()
    provider = ScriptedMockLLMProvider([LLMResponse(content="完成", model="mock/test")])
    loop = AgentLoop(
        store, provider, tools, JudgePipeline(), default_max_turns=2, timeout_seconds=1
    )
    await loop.run(context.session.id)
    assert store.finished
    assert tools.finalized == ["完成"]
    assert provider.requests[0].messages[0].role == "system"


async def test_agent_loop_executes_tool_and_can_terminate() -> None:
    context = make_context("worker")
    store = FakeStore(context)
    tools = FakeTools(terminate=True)
    call = ToolCall(id="call-1", name="lookup", arguments={})
    provider = ScriptedMockLLMProvider(
        [LLMResponse(content="", tool_calls=[call], model="mock/test")]
    )
    loop = AgentLoop(
        store, provider, tools, JudgePipeline(), default_max_turns=2, timeout_seconds=1
    )
    await loop.run(context.session.id)
    assert tools.calls == [call]
    assert store.messages[-1].role == "tool"
    assert store.checkpoints == ["after_tools"]


async def test_agent_loop_returns_invalid_tool_arguments_to_model_for_retry() -> None:
    context = make_context()
    store = FakeStore(context)
    tools = FakeTools()
    call = ToolCall(
        id="call-invalid",
        name="lookup",
        arguments={},
        argument_error="工具 lookup 的参数不是合法 JSON，请重新生成。",
    )
    provider = ScriptedMockLLMProvider(
        [
            LLMResponse(content="", tool_calls=[call], model="mock/test"),
            LLMResponse(content="修正完成", model="mock/test"),
        ]
    )
    loop = AgentLoop(
        store, provider, tools, JudgePipeline(), default_max_turns=2, timeout_seconds=1
    )

    await loop.run(context.session.id)

    tool_message = next(message for message in store.messages if message.role == "tool")
    assert "TOOL_ARGUMENTS_INVALID" in tool_message.content
    assert provider.requests[1].messages[-1].role == "tool"
    assert "TOOL_ARGUMENTS_INVALID" in provider.requests[1].messages[-1].content
    assert store.finished
    assert store.failed is None


async def test_agent_loop_persists_failure_after_turn_budget() -> None:
    context = make_context()
    store = FakeStore(context)
    provider = ScriptedMockLLMProvider(
        [
            LLMResponse(content="", model="mock/test"),
            LLMResponse(content="", model="mock/test"),
        ]
    )
    loop = AgentLoop(
        store,
        provider,
        FakeTools(),
        JudgePipeline(),
        default_max_turns=2,
        timeout_seconds=1,
    )
    await loop.run(context.session.id)
    assert store.failed is not None
    assert "最大" in str(store.failed) or "turn" in str(store.failed).lower()


async def test_agent_loop_enforces_tool_call_budget() -> None:
    context = make_context()
    context.session.budget["max_tool_calls"] = 0
    store = FakeStore(context)
    provider = ScriptedMockLLMProvider(
        [
            LLMResponse(
                content="",
                tool_calls=[ToolCall(id="call-1", name="lookup", arguments={})],
                model="mock/test",
            )
        ]
    )
    loop = AgentLoop(
        store,
        provider,
        FakeTools(),
        JudgePipeline(),
        default_max_turns=2,
        timeout_seconds=1,
    )
    await loop.run(context.session.id)
    assert store.failed is not None
    assert "tool calls" in str(store.failed)
    assert store.messages == []
