"""Unit tests for Colony runtime tool boundaries."""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from pytest import MonkeyPatch

from agentloom.agents.loop import AgentLoop, LoopContext
from agentloom.colony.notifier import ColonyEventNotifier
from agentloom.colony.runtime import (
    ColonyRuntime,
    FileAgentLoopStore,
    conversation_name_from_message,
    normalize_message_history,
)
from agentloom.colony.schemas import (
    ColonyRead,
    JsonObject,
    MessageRead,
    SessionRead,
    WorkerTask,
)
from agentloom.config import Settings
from agentloom.llm.base import LLMMessage, LLMResponse, ToolCall
from agentloom.llm.mock import SchemaMockLLMProvider, ScriptedMockLLMProvider
from agentloom.runtime.states import ColonyStatus, SessionStatus, WorkerStatus
from agentloom.storage import LocalColonyStore
from agentloom.tools.registry import create_builtin_tool_registry


def message(
    sequence: int,
    role: str,
    *,
    content: str = "",
    reasoning_content: str | None = None,
    tool_call_id: str | None = None,
    tool_calls: list[JsonObject] | None = None,
) -> MessageRead:
    return MessageRead(
        id=uuid4(),
        session_id=uuid4(),
        sequence=sequence,
        role=role,
        content=content,
        reasoning_content=reasoning_content,
        tool_call_id=tool_call_id,
        tool_calls=tool_calls or [],
        metadata={},
        created_at=datetime.now(UTC),
    )


def test_runtime_repairs_incomplete_tool_call_history() -> None:
    history = [
        message(
            1,
            "assistant",
            content="准备更新任务",
            tool_calls=[
                {"id": "call-1", "name": "task_update", "arguments": {}},
                {"id": "call-2", "name": "task_update", "arguments": {}},
            ],
        ),
        message(2, "tool", content="已更新一项", tool_call_id="call-1"),
        message(3, "user", content="新的 Worker 汇报"),
    ]

    normalized, repaired_groups = normalize_message_history(history)

    assert repaired_groups == 1
    assert [(item.role, item.content) for item in normalized] == [
        ("assistant", "准备更新任务"),
        ("user", "新的 Worker 汇报"),
    ]
    assert normalized[0].tool_calls == []


def test_runtime_preserves_complete_tool_call_history() -> None:
    history = [
        message(
            1,
            "assistant",
            tool_calls=[{"id": "call-1", "name": "task_update", "arguments": {}}],
            reasoning_content="  preserved reasoning  ",
        ),
        message(2, "tool", content="已更新", tool_call_id="call-1"),
    ]

    normalized, repaired_groups = normalize_message_history(history)

    assert repaired_groups == 0
    assert [item.role for item in normalized] == ["assistant", "tool"]
    assert normalized[0].tool_calls[0].id == "call-1"
    assert normalized[0].reasoning_content == "  preserved reasoning  "


def test_conversation_name_comes_from_first_message() -> None:
    assert conversation_name_from_message("  帮我\n制定计划  ") == "帮我 制定计划"
    assert conversation_name_from_message("一" * 40) == "一" * 32 + "…"


async def test_loop_store_injects_authoritative_worker_report_status(tmp_path: Path) -> None:
    store = LocalColonyStore(tmp_path)
    await store.initialize()
    _, queen = await store.create("Status", "", "general", "mock/schema", {})
    workers = await store.create_workers(
        queen.id,
        [WorkerTask(task="杭州"), WorkerTask(task="成都")],
        30,
    )
    loop_store = FileAgentLoopStore(store, ColonyEventNotifier())

    await store.finish_worker(
        workers[0].worker_session_id,
        WorkerStatus.COMPLETED,
        report={"summary": "杭州完成"},
    )
    await store.append_message(
        queen.id,
        LLMMessage(role="user", content="[WORKER_REPORT]\n杭州完成"),
        metadata={"worker_run_id": str(workers[0].id)},
    )

    partial = await loop_store.load(queen.id)
    assert partial is not None and partial.messages[-1].role == "system"
    partial_status = json.loads(partial.messages[-1].content.removeprefix("[WORKER_STATUS]\n"))
    assert partial_status["received_reports"] == 1
    assert partial_status["pending_workers"][0]["task"] == "成都"

    await store.finish_worker(
        workers[1].worker_session_id,
        WorkerStatus.COMPLETED,
        report={"summary": "成都完成"},
    )
    await store.append_message(
        queen.id,
        LLMMessage(role="user", content="[WORKER_REPORT]\n成都完成"),
        metadata={"worker_run_id": str(workers[1].id)},
    )

    complete = await loop_store.load(queen.id)
    assert complete is not None
    complete_status = json.loads(complete.messages[-1].content.removeprefix("[WORKER_STATUS]\n"))
    assert complete_status["received_reports"] == 2
    assert complete_status["pending_workers"] == []
    assert "不得声称仍在等待" in complete_status["instruction"]


async def test_background_task_failures_are_consumed_and_logged(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    events: list[tuple[str, dict[str, object]]] = []

    class RecordingLogger:
        def error(self, event: str, **values: object) -> None:
            events.append((event, values))

    def get_logger(*args: object, **kwargs: object) -> RecordingLogger:
        del args, kwargs
        return RecordingLogger()

    monkeypatch.setattr("agentloom.colony.runtime.structlog.get_logger", get_logger)
    settings = Settings(environment="test", storage_root=tmp_path)
    runtime = ColonyRuntime(
        LocalColonyStore(tmp_path),
        SchemaMockLLMProvider(),
        ColonyEventNotifier(),
        settings,
        create_builtin_tool_registry(),
    )

    async def fail() -> None:
        raise RuntimeError("token=secret-value")

    runtime._schedule(fail())  # pyright: ignore[reportPrivateUsage]
    while runtime._background_tasks:  # pyright: ignore[reportPrivateUsage]
        await asyncio.sleep(0)

    assert events == [
        (
            "background_task_failed",
            {"error_type": "RuntimeError", "error": "token=[REDACTED]"},
        )
    ]


async def test_each_worker_runs_with_an_independent_agent_loop(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    store = LocalColonyStore(tmp_path)
    await store.initialize()
    _, queen = await store.create("Independent loops", "", "general", "mock/schema", {})
    workers = await store.create_workers(
        queen.id,
        [WorkerTask(task="杭州"), WorkerTask(task="成都")],
        30,
    )
    runtime = ColonyRuntime(
        store,
        SchemaMockLLMProvider(),
        ColonyEventNotifier(),
        Settings(environment="test", storage_root=tmp_path),
        create_builtin_tool_registry(),
    )
    queen_loop = runtime._get_queen_loop(queen.id)  # pyright: ignore[reportPrivateUsage]
    built_loops: list[AgentLoop] = []
    runs: list[tuple[UUID, AgentLoop]] = []
    original_build_worker_loop = runtime._build_worker_loop  # pyright: ignore[reportPrivateUsage]

    def build_worker_loop() -> AgentLoop:
        loop = original_build_worker_loop()
        built_loops.append(loop)
        return loop

    async def run_serial(session_id: UUID, loop: AgentLoop) -> None:
        runs.append((session_id, loop))

    monkeypatch.setattr(runtime, "_build_worker_loop", build_worker_loop)
    monkeypatch.setattr(runtime, "_run_serial", run_serial)

    await asyncio.gather(*(runtime._run_worker(worker.id) for worker in workers))  # pyright: ignore[reportPrivateUsage]

    assert len(built_loops) == 2
    assert built_loops[0] is not built_loops[1]
    assert {session_id for session_id, _ in runs} == {
        worker.worker_session_id for worker in workers
    }
    assert {id(loop) for _, loop in runs} == {id(loop) for loop in built_loops}
    assert all(loop is not queen_loop for loop in built_loops)


def test_each_queen_session_has_an_independent_reusable_agent_loop(tmp_path: Path) -> None:
    runtime = ColonyRuntime(
        LocalColonyStore(tmp_path),
        SchemaMockLLMProvider(),
        ColonyEventNotifier(),
        Settings(environment="test", storage_root=tmp_path),
        create_builtin_tool_registry(),
    )
    first_session_id = uuid4()
    second_session_id = uuid4()

    first_loop = runtime._get_queen_loop(first_session_id)  # pyright: ignore[reportPrivateUsage]

    assert runtime._get_queen_loop(first_session_id) is first_loop  # pyright: ignore[reportPrivateUsage]
    assert runtime._get_queen_loop(second_session_id) is not first_loop  # pyright: ignore[reportPrivateUsage]


async def test_budget_exhausted_worker_reports_partial_and_wakes_queen(
    tmp_path: Path,
) -> None:
    store = LocalColonyStore(tmp_path)
    await store.initialize()
    colony, queen = await store.create("Budget", "", "general", "mock/schema", {})
    worker = (
        await store.create_workers(
            queen.id,
            [WorkerTask(task="整理资料")],
            30,
        )
    )[0]
    worker_session = await store.get_session(worker.worker_session_id)
    assert worker_session is not None
    runtime = ColonyRuntime(
        store,
        SchemaMockLLMProvider(),
        ColonyEventNotifier(),
        Settings(environment="test", storage_root=tmp_path),
        create_builtin_tool_registry(),
    )
    runtime._stopping = True  # pyright: ignore[reportPrivateUsage]

    await runtime.finalize_budget_exhausted(
        LoopContext(session=worker_session, colony=colony, messages=[]),
        "工具预算已耗尽，已保留当前进度。",
        "tool_calls",
    )

    saved_worker = await store.get_worker_for_session(worker.worker_session_id)
    assert saved_worker is not None
    assert saved_worker.status is WorkerStatus.PARTIAL
    assert saved_worker.report == {
        "status": "partial",
        "summary": "工具预算已耗尽，已保留当前进度。",
        "data": {"budget_reason": "tool_calls"},
    }
    saved_queen = await store.get_session(queen.id)
    assert saved_queen is not None
    assert saved_queen.status is SessionStatus.QUEUED
    queen_messages = await store.list_messages(queen.id)
    assert queen_messages is not None
    assert queen_messages[-1].content.startswith("[WORKER_REPORT]\n")


async def test_budget_grace_report_keeps_worker_session_completed(tmp_path: Path) -> None:
    store = LocalColonyStore(tmp_path)
    await store.initialize()
    _, queen = await store.create("Budget report", "", "general", "mock/schema", {})
    worker = (await store.create_workers(queen.id, [WorkerTask(task="整理资料")], 30))[0]
    await store.set_session_status(
        worker.worker_session_id,
        SessionStatus.QUEUED,
        cursor={
            "iteration": 8,
            "phase": "budget_grace",
            "budget_reason": "model_turns",
            "budget_tool_calls": 2,
            "grace_turn": 0,
        },
    )
    provider = ScriptedMockLLMProvider(
        [
            LLMResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        id="report",
                        name="report_to_parent",
                        arguments={
                            "status": "partial",
                            "summary": "已完成资料整理，剩余对比待补充。",
                            "data": {},
                        },
                    )
                ],
                model="mock/test",
            )
        ]
    )
    runtime = ColonyRuntime(
        store,
        provider,
        ColonyEventNotifier(),
        Settings(environment="test", storage_root=tmp_path),
        create_builtin_tool_registry(),
    )
    runtime._stopping = True  # pyright: ignore[reportPrivateUsage]

    await runtime._build_worker_loop().run(worker.worker_session_id)  # pyright: ignore[reportPrivateUsage]

    saved_worker = await store.get_worker_for_session(worker.worker_session_id)
    saved_session = await store.get_session(worker.worker_session_id)
    assert saved_worker is not None and saved_worker.status is WorkerStatus.PARTIAL
    assert saved_session is not None and saved_session.status is SessionStatus.COMPLETED
    assert saved_session.cursor == {"iteration": 0, "phase": "completed"}


async def test_failed_worker_synthesizes_report_and_wakes_queen(tmp_path: Path) -> None:
    store = LocalColonyStore(tmp_path)
    await store.initialize()
    _, queen = await store.create("Failed worker", "", "general", "mock/schema", {})
    worker = (await store.create_workers(queen.id, [WorkerTask(task="整理资料")], 30))[0]
    runtime = ColonyRuntime(
        store,
        ScriptedMockLLMProvider([]),
        ColonyEventNotifier(),
        Settings(environment="test", storage_root=tmp_path),
        create_builtin_tool_registry(),
    )
    runtime._stopping = True  # pyright: ignore[reportPrivateUsage]

    await runtime._run_worker(worker.id)  # pyright: ignore[reportPrivateUsage]
    await runtime._ensure_worker_terminal_report(  # pyright: ignore[reportPrivateUsage]
        worker.worker_session_id
    )

    saved_worker = await store.get_worker_for_session(worker.worker_session_id)
    assert saved_worker is not None
    assert saved_worker.status is WorkerStatus.FAILED
    assert saved_worker.report is not None
    assert saved_worker.report["status"] == "failed"
    assert saved_worker.report["data"] == {
        "synthetic_report": True,
        "worker_status": "failed",
        "error_code": "AGENT_LOOP_FAILED",
    }
    saved_queen = await store.get_session(queen.id)
    assert saved_queen is not None and saved_queen.status is SessionStatus.QUEUED
    queen_messages = await store.list_messages(queen.id)
    assert queen_messages is not None and len(queen_messages) == 1
    assert queen_messages[0].metadata == {"worker_run_id": str(worker.id)}
    report = json.loads(queen_messages[0].content.removeprefix("[WORKER_REPORT]\n"))
    assert report == saved_worker.report

    queen_context = await FileAgentLoopStore(store, ColonyEventNotifier()).load(queen.id)
    assert queen_context is not None
    worker_status = json.loads(queen_context.messages[-1].content.removeprefix("[WORKER_STATUS]\n"))
    assert worker_status["received_reports"] == 1
    assert worker_status["pending_workers"] == []
    assert "不得声称仍在等待" in worker_status["instruction"]


async def test_timed_out_worker_synthesizes_report_and_wakes_queen(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    store = LocalColonyStore(tmp_path)
    await store.initialize()
    _, queen = await store.create("Timed out worker", "", "general", "mock/schema", {})
    worker = (await store.create_workers(queen.id, [WorkerTask(task="调研城市")], 30))[0]
    runtime = ColonyRuntime(
        store,
        SchemaMockLLMProvider(),
        ColonyEventNotifier(),
        Settings(environment="test", storage_root=tmp_path),
        create_builtin_tool_registry(),
    )
    runtime._stopping = True  # pyright: ignore[reportPrivateUsage]

    async def time_out(session_id: UUID, loop: AgentLoop) -> None:
        del session_id, loop
        raise TimeoutError

    monkeypatch.setattr(runtime, "_run_serial", time_out)

    await runtime._run_worker(worker.id)  # pyright: ignore[reportPrivateUsage]

    saved_worker = await store.get_worker_for_session(worker.worker_session_id)
    assert saved_worker is not None
    assert saved_worker.status is WorkerStatus.TIMED_OUT
    assert saved_worker.report is not None
    assert saved_worker.report["status"] == "failed"
    assert saved_worker.report["data"] == {
        "synthetic_report": True,
        "worker_status": "timed_out",
        "error_code": "WORKER_TIMEOUT",
    }
    saved_queen = await store.get_session(queen.id)
    assert saved_queen is not None and saved_queen.status is SessionStatus.QUEUED
    queen_messages = await store.list_messages(queen.id)
    assert queen_messages is not None and len(queen_messages) == 1
    assert queen_messages[0].content.startswith("[WORKER_REPORT]\n")


async def test_runtime_exposes_actor_tools_and_executes_builtin(tmp_path: Path) -> None:
    settings = Settings(environment="test", storage_root=tmp_path)
    runtime = ColonyRuntime(
        LocalColonyStore(tmp_path),
        SchemaMockLLMProvider(),
        ColonyEventNotifier(),
        settings,
        create_builtin_tool_registry(),
    )
    queen_names = {item.name for item in runtime.definitions("queen")}
    worker_names = {item.name for item in runtime.definitions("worker")}
    assert {"run_worker", "web_search", "read_task_context"} <= queen_names
    assert "report_to_parent" in worker_names
    assert "run_worker" not in worker_names

    context = make_context()
    result = await runtime.execute(
        context,
        ToolCall(id="search-1", name="web_search", arguments={"query": "AgentLoom"}),
    )
    assert isinstance(result.value, dict)
    assert result.value["query"] == "AgentLoom"

    invalid_result = await runtime.execute(
        context,
        ToolCall(
            id="invalid-task",
            name="task_create",
            arguments={},
            argument_error="工具 task_create 的参数不是合法 JSON，请重新生成。",
        ),
    )
    assert invalid_result.value == {
        "error": {
            "code": "TOOL_ARGUMENTS_INVALID",
            "message": "工具 task_create 的参数不是合法 JSON，请重新生成。",
        }
    }


def make_context() -> LoopContext:
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
            model="mock/schema",
            settings={},
            queen_session_id=session_id,
            created_at=now,
            updated_at=now,
        ),
        session=SessionRead(
            id=session_id,
            colony_id=colony_id,
            parent_session_id=None,
            actor_type="queen",
            status=SessionStatus.IDLE,
            park_reason=None,
            task={"goal": "研究"},
            cursor={},
            budget={},
            usage={},
            created_at=now,
            updated_at=now,
            ended_at=None,
        ),
        messages=[],
    )
