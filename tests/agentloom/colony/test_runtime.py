"""Unit tests for Colony runtime tool boundaries."""

from datetime import UTC, datetime
from uuid import uuid4

from agentloom.agents.loop import LoopContext
from agentloom.colony.notifier import ColonyEventNotifier
from agentloom.colony.runtime import ColonyRuntime, normalize_message_history
from agentloom.colony.schemas import ColonyRead, JsonObject, MessageRead, SessionRead
from agentloom.config import Settings
from agentloom.db.session import DatabaseSessionManager
from agentloom.llm.base import ToolCall
from agentloom.llm.mock import SchemaMockLLMProvider
from agentloom.runtime.states import ColonyStatus, SessionStatus
from agentloom.tools.registry import create_builtin_tool_registry


def message(
    sequence: int,
    role: str,
    *,
    content: str = "",
    tool_call_id: str | None = None,
    tool_calls: list[JsonObject] | None = None,
) -> MessageRead:
    return MessageRead(
        id=uuid4(),
        session_id=uuid4(),
        sequence=sequence,
        role=role,
        content=content,
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
        ),
        message(2, "tool", content="已更新", tool_call_id="call-1"),
    ]

    normalized, repaired_groups = normalize_message_history(history)

    assert repaired_groups == 0
    assert [item.role for item in normalized] == ["assistant", "tool"]
    assert normalized[0].tool_calls[0].id == "call-1"


async def test_runtime_exposes_actor_tools_and_executes_builtin() -> None:
    settings = Settings(environment="test")
    database = DatabaseSessionManager(settings.database_url)
    runtime = ColonyRuntime(
        database.session_factory,
        SchemaMockLLMProvider(),
        ColonyEventNotifier(),
        settings,
        create_builtin_tool_registry(),
    )
    try:
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
    finally:
        await database.dispose()


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
