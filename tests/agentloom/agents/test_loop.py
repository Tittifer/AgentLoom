"""Tests for the unified Queen/Worker AgentLoop."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from pytest import MonkeyPatch

from agentloom.agents.judge import JudgePipeline
from agentloom.agents.loop import (
    AgentLoop,
    BudgetReason,
    LoopContext,
    ToolExecutionResult,
)
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
        self.checkpoint_cursors: list[dict[str, object]] = []
        self.finished = False
        self.failed: Exception | None = None
        self.deltas: list[tuple[UUID, str]] = []
        self.cancelled_streams: list[UUID] = []

    async def load(self, session_id):  # type: ignore[no-untyped-def]
        return self.context if session_id == self.context.session.id else None

    async def mark_running(self, context: LoopContext) -> bool:
        return context is self.context

    async def append_message(
        self,
        context: LoopContext,
        message: LLMMessage,
        event_type: str,
        message_id: UUID | None = None,
    ) -> MessageRead:
        del context, event_type
        self.messages.append(message)
        now = datetime.now(UTC)
        return MessageRead(
            id=message_id or uuid4(),
            session_id=self.context.session.id,
            sequence=len(self.messages),
            role=message.role,
            content=message.content,
            tool_call_id=message.tool_call_id,
            tool_calls=[call.model_dump(mode="json") for call in message.tool_calls],
            metadata={},
            created_at=now,
        )

    async def publish_message_delta(
        self, context: LoopContext, message_id: UUID, delta: str
    ) -> None:
        del context
        self.deltas.append((message_id, delta))

    async def cancel_message_stream(self, context: LoopContext, message_id: UUID) -> None:
        del context
        self.cancelled_streams.append(message_id)

    async def checkpoint(
        self,
        context: LoopContext,
        iteration: int,
        phase: str,
        usage: dict[str, int],
        *,
        budget_tool_calls: int = 0,
        budget_reason: BudgetReason | None = None,
        grace_turn: int = 0,
    ) -> None:
        del context, usage
        self.checkpoints.append(phase)
        self.checkpoint_cursors.append(
            {
                "iteration": iteration,
                "phase": phase,
                "budget_tool_calls": budget_tool_calls,
                "budget_reason": budget_reason,
                "grace_turn": grace_turn,
            }
        )

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
        self.budget_finalized: list[tuple[str, BudgetReason]] = []

    def definitions(self, actor_type):  # type: ignore[no-untyped-def]
        definitions = [
            ToolDefinition(name="lookup", description="查询", parameters={"type": "object"})
        ]
        if actor_type == "worker":
            definitions.extend(
                [
                    ToolDefinition(
                        name="report_to_parent",
                        description="汇报",
                        parameters={"type": "object"},
                    ),
                    ToolDefinition(
                        name="tracker_upsert",
                        description="保存进度",
                        parameters={"type": "object"},
                    ),
                    ToolDefinition(
                        name="task_update",
                        description="更新任务",
                        parameters={"type": "object"},
                    ),
                ]
            )
        return definitions

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
        return ToolExecutionResult(
            {"ok": True},
            terminate=self.terminate or tool_call.name == "report_to_parent",
        )

    async def finalize_text(self, context: LoopContext, content: str) -> None:
        del context
        self.finalized.append(content)

    async def finalize_budget_exhausted(
        self,
        context: LoopContext,
        content: str,
        reason: BudgetReason,
    ) -> None:
        del context
        self.budget_finalized.append((content, reason))


class RecordingLogger:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    def info(self, event: str, **values: object) -> None:
        self.events.append((event, values))


async def test_agent_loop_finishes_visible_response() -> None:
    context = make_context()
    store = FakeStore(context)
    tools = FakeTools()
    provider = ScriptedMockLLMProvider(
        [LLMResponse(content="完成", reasoning_content="内部推理", model="mock/test")]
    )
    loop = AgentLoop(
        store, provider, tools, JudgePipeline(), default_max_turns=2, timeout_seconds=1
    )
    await loop.run(context.session.id)
    assert store.finished
    assert tools.finalized == ["完成"]
    assert store.messages[0].reasoning_content == "内部推理"
    assert provider.requests[0].messages[0].role == "system"
    assert [delta for _, delta in store.deltas] == ["完成"]


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
    assert store.checkpoints == []
    assert store.finished
    assert store.deltas == []


async def test_agent_loop_logs_turn_usage_to_console_logger(monkeypatch: MonkeyPatch) -> None:
    logger = RecordingLogger()

    def get_logger(*args: object, **kwargs: object) -> RecordingLogger:
        del args, kwargs
        return logger

    monkeypatch.setattr("agentloom.agents.loop.structlog.get_logger", get_logger)
    context = make_context()
    store = FakeStore(context)
    provider = ScriptedMockLLMProvider(
        [
            LLMResponse(
                content="完成",
                reasoning_content="不得写入日志",
                input_tokens=11,
                output_tokens=7,
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

    assert logger.events == [
        (
            "agent_turn_usage",
            {
                "session_id": str(context.session.id),
                "actor_type": "queen",
                "model": "mock/test",
                "iteration": 1,
                "input_tokens": 11,
                "output_tokens": 7,
                "requested_tool_calls": 0,
                "total_input_tokens": 11,
                "total_output_tokens": 7,
                "total_tool_calls": 0,
            },
        )
    ]


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


async def test_agent_loop_uses_grace_response_after_turn_budget() -> None:
    context = make_context()
    store = FakeStore(context)
    tools = FakeTools()
    provider = ScriptedMockLLMProvider(
        [
            LLMResponse(content="", model="mock/test"),
            LLMResponse(content="", model="mock/test"),
            LLMResponse(content="已整理当前结果", model="mock/test"),
        ]
    )
    loop = AgentLoop(
        store,
        provider,
        tools,
        JudgePipeline(),
        default_max_turns=2,
        timeout_seconds=1,
    )
    await loop.run(context.session.id)
    assert store.failed is None
    assert store.finished
    assert tools.budget_finalized == [("已整理当前结果", "model_turns")]
    assert provider.requests[-1].tools == []
    assert "budget_grace" in store.checkpoints


async def test_agent_loop_persists_mark_running_failure() -> None:
    context = make_context()

    class MarkRunningFailureStore(FakeStore):
        async def mark_running(self, context: LoopContext) -> bool:
            del context
            raise PermissionError("session metadata is locked")

    store = MarkRunningFailureStore(context)
    loop = AgentLoop(
        store,
        ScriptedMockLLMProvider([]),
        FakeTools(),
        JudgePipeline(),
        default_max_turns=2,
        timeout_seconds=1,
    )

    await loop.run(context.session.id)

    assert isinstance(store.failed, PermissionError)


async def test_agent_loop_enforces_tool_call_budget() -> None:
    context = make_context()
    context.session.budget["max_tool_calls"] = 0
    store = FakeStore(context)
    tools = FakeTools()
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
        tools,
        JudgePipeline(),
        default_max_turns=2,
        timeout_seconds=1,
    )
    await loop.run(context.session.id)
    assert store.failed is None
    assert store.finished
    assert tools.calls == []
    assert tools.budget_finalized[0][1] == "tool_calls"
    tool_result = next(message for message in store.messages if message.role == "tool")
    assert "TOOL_NOT_ALLOWED_IN_GRACE" in tool_result.content


async def test_agent_loop_skips_only_tool_calls_beyond_remaining_budget() -> None:
    context = make_context()
    context.session.budget["max_tool_calls"] = 1
    store = FakeStore(context)
    tools = FakeTools()
    calls = [
        ToolCall(id="call-1", name="lookup", arguments={"item": 1}),
        ToolCall(id="call-2", name="lookup", arguments={"item": 2}),
    ]
    provider = ScriptedMockLLMProvider(
        [
            LLMResponse(content="", tool_calls=calls, model="mock/test"),
            LLMResponse(content="已基于现有资料收尾", model="mock/test"),
        ]
    )
    loop = AgentLoop(
        store,
        provider,
        tools,
        JudgePipeline(),
        default_max_turns=2,
        timeout_seconds=1,
    )

    await loop.run(context.session.id)

    assert tools.calls == [calls[0]]
    tool_results = [message for message in store.messages if message.role == "tool"]
    assert len(tool_results) == 2
    assert "TOOL_BUDGET_EXHAUSTED" in tool_results[1].content
    assert tools.budget_finalized == [("已基于现有资料收尾", "tool_calls")]
    assert store.checkpoint_cursors[-1]["budget_tool_calls"] == 1


async def test_worker_can_report_during_turn_budget_grace() -> None:
    context = make_context("worker")
    context.session.budget["max_turns"] = 1
    store = FakeStore(context)
    tools = FakeTools()
    provider = ScriptedMockLLMProvider(
        [
            LLMResponse(
                content="",
                tool_calls=[ToolCall(id="lookup", name="lookup", arguments={})],
                model="mock/test",
            ),
            LLMResponse(
                content="",
                tool_calls=[ToolCall(id="report", name="report_to_parent", arguments={})],
                model="mock/test",
            ),
        ]
    )
    loop = AgentLoop(
        store,
        provider,
        tools,
        JudgePipeline(),
        default_max_turns=1,
        timeout_seconds=1,
    )

    await loop.run(context.session.id)

    assert [call.name for call in tools.calls] == ["lookup", "report_to_parent"]
    assert {definition.name for definition in provider.requests[-1].tools} == {
        "report_to_parent",
        "tracker_upsert",
        "task_update",
    }
    assert store.failed is None
    assert store.finished


async def test_worker_resumes_inside_budget_grace() -> None:
    context = make_context("worker")
    context.session.cursor = {
        "iteration": 2,
        "phase": "budget_grace",
        "budget_reason": "tool_calls",
        "budget_tool_calls": 30,
        "grace_turn": 1,
    }
    store = FakeStore(context)
    tools = FakeTools()
    provider = ScriptedMockLLMProvider(
        [
            LLMResponse(
                content="",
                tool_calls=[ToolCall(id="report", name="report_to_parent", arguments={})],
                model="mock/test",
            )
        ]
    )
    loop = AgentLoop(
        store,
        provider,
        tools,
        JudgePipeline(),
        default_max_turns=2,
        timeout_seconds=1,
    )

    await loop.run(context.session.id)

    assert len(provider.requests) == 1
    assert [call.name for call in tools.calls] == ["report_to_parent"]
    assert store.failed is None


async def test_queen_tool_budget_is_per_activation_not_lifetime_usage() -> None:
    context = make_context()
    context.session.budget.update({"max_turns": 1, "max_tool_calls": 1})
    context.session.usage["tool_calls"] = 100
    store = FakeStore(context)
    tools = FakeTools()
    provider = ScriptedMockLLMProvider(
        [
            LLMResponse(
                content="",
                tool_calls=[ToolCall(id="lookup", name="lookup", arguments={})],
                model="mock/test",
            ),
            LLMResponse(content="本轮总结", model="mock/test"),
        ]
    )
    loop = AgentLoop(
        store,
        provider,
        tools,
        JudgePipeline(),
        default_max_turns=1,
        timeout_seconds=1,
    )

    await loop.run(context.session.id)

    assert [call.name for call in tools.calls] == ["lookup"]
    assert tools.budget_finalized == [("本轮总结", "model_turns")]
    assert store.failed is None
