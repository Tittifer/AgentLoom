"""Tests for model, tool, reviewer, and retry worker orchestration."""

from collections.abc import Sequence
from uuid import UUID, uuid4

from pydantic import JsonValue

from agentloom.agents.reviewer import DeterministicReviewer, ReviewResult
from agentloom.agents.worker import Worker
from agentloom.db.base import JsonObject
from agentloom.llm.base import (
    LLMMessage,
    LLMProviderError,
    LLMResponse,
    ToolCall,
)
from agentloom.llm.mock import ScriptedMockLLMProvider
from agentloom.runtime.run import NodeExecutionContext
from agentloom.runtime.workflow import WorkflowNodeRead
from agentloom.tools.registry import create_builtin_tool_registry


class RecordingWorkerStore:
    def __init__(self, contexts: Sequence[NodeExecutionContext]) -> None:
        self.contexts = list(contexts)
        self.load_index = 0
        self.started: list[int] = []
        self.messages: list[LLMMessage] = []
        self.reviewing: list[dict[str, JsonValue]] = []
        self.accepted: list[dict[str, JsonValue]] = []
        self.retried: list[ReviewResult] = []
        self.failures: list[JsonObject] = []

    async def load_context(self, run_id: UUID, node_key: str) -> NodeExecutionContext | None:
        del run_id, node_key
        if self.load_index >= len(self.contexts):
            return None
        context = self.contexts[self.load_index]
        self.load_index += 1
        return context

    async def start_attempt(
        self,
        context: NodeExecutionContext,
        messages: Sequence[LLMMessage],
    ) -> bool:
        self.started.append(context.attempt)
        self.messages.extend(messages)
        return True

    async def append_message(self, node_run_id: UUID, message: LLMMessage) -> None:
        del node_run_id
        self.messages.append(message)

    async def mark_reviewing(
        self,
        context: NodeExecutionContext,
        output: dict[str, JsonValue],
        usage: JsonObject,
    ) -> bool:
        del context, usage
        self.reviewing.append(output)
        return True

    async def accept(
        self,
        context: NodeExecutionContext,
        output: dict[str, JsonValue],
        review: ReviewResult,
    ) -> bool:
        del context, review
        self.accepted.append(output)
        return True

    async def retry(
        self,
        context: NodeExecutionContext,
        review: ReviewResult,
    ) -> bool:
        del context
        self.retried.append(review)
        return True

    async def fail(
        self,
        context: NodeExecutionContext,
        error: JsonObject,
        *,
        review: ReviewResult | None = None,
        usage: JsonObject | None = None,
    ) -> bool:
        del context, review, usage
        self.failures.append(error)
        return True


def execution_context(
    attempt: int = 1,
    *,
    tools: list[str] | None = None,
    previous_feedback: str | None = None,
    max_retries: int = 1,
) -> NodeExecutionContext:
    return NodeExecutionContext(
        run_id=RUN_ID,
        node_run_id=uuid4(),
        node_key="research",
        attempt=attempt,
        task_goal="Research a product",
        task_context={"language": "en"},
        node=WorkflowNodeRead(
            id=uuid4(),
            key="research",
            name="Research",
            role="researcher",
            description="Collect facts",
            system_prompt="Return facts",
            depends_on=[],
            tools=tools or [],
            output_schema={
                "type": "object",
                "required": ["summary"],
                "properties": {"summary": {"type": "string"}},
            },
            review_criteria=None,
            sort_order=0,
        ),
        upstream_outputs={},
        previous_feedback=previous_feedback,
        max_retries=max_retries,
    )


def worker(store: RecordingWorkerStore, responses: Sequence[LLMResponse | Exception]) -> Worker:
    return Worker(
        store,
        ScriptedMockLLMProvider(responses),
        DeterministicReviewer(),
        create_builtin_tool_registry(),
        model="mock/test",
        max_turns=3,
    )


RUN_ID = uuid4()


async def test_worker_retries_invalid_output_then_completes_next_attempt() -> None:
    store = RecordingWorkerStore(
        [
            execution_context(),
            execution_context(attempt=2, previous_feedback="Required string must not be empty"),
        ]
    )
    executor = worker(
        store,
        [
            LLMResponse(model="mock/test", structured_output={"summary": ""}),
            LLMResponse(model="mock/test", structured_output={"summary": "valid"}),
        ],
    )

    await executor.execute(RUN_ID, "research")

    assert store.started == [1, 2]
    assert len(store.retried) == 1
    assert store.accepted == [{"summary": "valid"}]
    assert [message.role for message in store.messages].count("reviewer") == 2


async def test_worker_executes_allowed_tool_and_passes_result_to_next_turn() -> None:
    store = RecordingWorkerStore([execution_context(tools=["read_task_context"])])
    provider = ScriptedMockLLMProvider(
        [
            LLMResponse(
                model="mock/test",
                tool_calls=[ToolCall(id="call-1", name="read_task_context", arguments={})],
            ),
            LLMResponse(model="mock/test", structured_output={"summary": "valid"}),
        ]
    )
    executor = Worker(
        store,
        provider,
        DeterministicReviewer(),
        create_builtin_tool_registry(),
        model="mock/test",
    )

    await executor.execute(RUN_ID, "research")

    assert store.accepted == [{"summary": "valid"}]
    assert any(
        message.role == "tool" and "language" in message.content for message in store.messages
    )
    assert provider.requests[1].messages[-1].role == "tool"


async def test_worker_records_unauthorized_tool_error_for_the_model() -> None:
    store = RecordingWorkerStore([execution_context()])
    provider = ScriptedMockLLMProvider(
        [
            LLMResponse(
                model="mock/test",
                tool_calls=[ToolCall(id="call-1", name="shell", arguments={})],
            ),
            LLMResponse(model="mock/test", structured_output={"summary": "valid"}),
        ]
    )
    executor = Worker(
        store,
        provider,
        DeterministicReviewer(),
        create_builtin_tool_registry(),
        model="mock/test",
    )

    await executor.execute(RUN_ID, "research")

    tool_message = next(message for message in store.messages if message.role == "tool")
    assert "TOOL_NOT_ALLOWED" in tool_message.content
    assert store.accepted == [{"summary": "valid"}]


async def test_worker_fails_when_review_retries_are_exhausted() -> None:
    store = RecordingWorkerStore([execution_context(max_retries=0)])
    executor = worker(
        store,
        [LLMResponse(model="mock/test", structured_output={"summary": ""})],
    )

    await executor.execute(RUN_ID, "research")

    assert store.failures[0]["code"] == "REVIEW_RETRIES_EXHAUSTED"


async def test_worker_converts_provider_error_to_failed_state() -> None:
    store = RecordingWorkerStore([execution_context()])
    executor = worker(store, [LLMProviderError("provider unavailable")])

    await executor.execute(RUN_ID, "research")

    assert store.failures[0]["code"] == "WORKER_EXECUTION_FAILED"


async def test_worker_fails_after_bounded_content_only_turns() -> None:
    store = RecordingWorkerStore([execution_context()])
    executor = worker(
        store,
        [LLMResponse(model="mock/test", content="not json") for _ in range(3)],
    )

    await executor.execute(RUN_ID, "research")

    assert store.failures[0]["code"] == "MAX_TURNS_EXCEEDED"
