"""Bounded worker loop and transactional database execution store."""

import json
from collections.abc import Sequence
from typing import Literal, Protocol
from uuid import UUID

import structlog
from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentloom.agents.prompts import build_worker_messages
from agentloom.agents.reviewer import DeterministicReviewer, ReviewResult
from agentloom.db.base import JsonObject
from agentloom.llm.base import LLMMessage, LLMProvider, LLMRequest, ToolCall
from agentloom.repositories.events import RunEventRepository
from agentloom.repositories.messages import MessageRepository
from agentloom.repositories.runs import RunRepository
from agentloom.runtime.run import NodeExecutionContext
from agentloom.services.event_service import EventService, RunEventNotifier
from agentloom.tools.base import ToolContext, ToolError
from agentloom.tools.registry import ToolRegistry

AttemptResult = Literal["completed", "retry", "failed", "stale"]


class WorkerStore(Protocol):
    """Committed persistence operations required by the worker loop."""

    async def load_context(
        self,
        run_id: UUID,
        node_key: str,
    ) -> NodeExecutionContext | None: ...

    async def start_attempt(
        self,
        context: NodeExecutionContext,
        messages: Sequence[LLMMessage],
    ) -> bool: ...

    async def append_message(
        self,
        node_run_id: UUID,
        message: LLMMessage,
    ) -> None: ...

    async def mark_reviewing(
        self,
        context: NodeExecutionContext,
        output: dict[str, JsonValue],
        usage: JsonObject,
    ) -> bool: ...

    async def accept(
        self,
        context: NodeExecutionContext,
        output: dict[str, JsonValue],
        review: ReviewResult,
    ) -> bool: ...

    async def retry(
        self,
        context: NodeExecutionContext,
        review: ReviewResult,
    ) -> bool: ...

    async def fail(
        self,
        context: NodeExecutionContext,
        error: JsonObject,
        *,
        review: ReviewResult | None = None,
        usage: JsonObject | None = None,
    ) -> bool: ...


class DatabaseWorkerStore:
    """Persist every worker transition and its event atomically."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        event_notifier: RunEventNotifier,
    ) -> None:
        self._session_factory = session_factory
        self._event_notifier = event_notifier

    async def load_context(
        self,
        run_id: UUID,
        node_key: str,
    ) -> NodeExecutionContext | None:
        async with self._session_factory() as session:
            return await RunRepository(session).get_node_execution_context(run_id, node_key)

    async def start_attempt(
        self,
        context: NodeExecutionContext,
        messages: Sequence[LLMMessage],
    ) -> bool:
        transitioned = False
        async with self._session_factory.begin() as session:
            repository = RunRepository(session)
            transitioned = await repository.mark_node_running(
                context.run_id,
                context.node_key,
                {
                    "task_goal": context.task_goal,
                    "task_context": context.task_context,
                    "upstream_outputs": context.upstream_outputs,
                    "previous_feedback": context.previous_feedback,
                },
            )
            if transitioned:
                message_repository = MessageRepository(session)
                for message in messages:
                    await message_repository.create(
                        context.node_run_id,
                        message.role,
                        message.content,
                        _tool_call_payloads(message.tool_calls),
                    )
                await EventService(RunEventRepository(session)).append(
                    context.run_id,
                    "node.started",
                    node_key=context.node_key,
                    payload={"status": "running", "attempt": context.attempt},
                )
        if transitioned:
            await self._event_notifier.notify(context.run_id)
        return transitioned

    async def append_message(self, node_run_id: UUID, message: LLMMessage) -> None:
        async with self._session_factory.begin() as session:
            await MessageRepository(session).create(
                node_run_id,
                message.role,
                message.content,
                _tool_call_payloads(message.tool_calls),
            )

    async def mark_reviewing(
        self,
        context: NodeExecutionContext,
        output: dict[str, JsonValue],
        usage: JsonObject,
    ) -> bool:
        transitioned = False
        async with self._session_factory.begin() as session:
            transitioned = await RunRepository(session).mark_node_reviewing(
                context.run_id,
                context.node_key,
                output,
                usage,
            )
            if transitioned:
                await EventService(RunEventRepository(session)).append(
                    context.run_id,
                    "llm.usage_recorded",
                    node_key=context.node_key,
                    payload=usage,
                )
        if transitioned:
            await self._event_notifier.notify(context.run_id)
        return transitioned

    async def accept(
        self,
        context: NodeExecutionContext,
        output: dict[str, JsonValue],
        review: ReviewResult,
    ) -> bool:
        transitioned = False
        async with self._session_factory.begin() as session:
            transitioned = await RunRepository(session).complete_node(
                context.run_id,
                context.node_key,
                output,
                review.model_dump(mode="json"),
            )
            if transitioned:
                events = EventService(RunEventRepository(session))
                await events.append(
                    context.run_id,
                    "node.reviewed",
                    node_key=context.node_key,
                    payload={"decision": review.decision, "score": review.score},
                )
                await events.append(
                    context.run_id,
                    "node.completed",
                    node_key=context.node_key,
                    payload={"status": "completed", "attempt": context.attempt},
                )
        if transitioned:
            await self._event_notifier.notify(context.run_id)
        return transitioned

    async def retry(
        self,
        context: NodeExecutionContext,
        review: ReviewResult,
    ) -> bool:
        transitioned = False
        async with self._session_factory.begin() as session:
            transitioned = await RunRepository(session).retry_node(
                context.run_id,
                context.node_key,
                review.model_dump(mode="json"),
            )
            if transitioned:
                events = EventService(RunEventRepository(session))
                await events.append(
                    context.run_id,
                    "node.reviewed",
                    node_key=context.node_key,
                    payload={"decision": review.decision, "score": review.score},
                )
                await events.append(
                    context.run_id,
                    "node.retrying",
                    node_key=context.node_key,
                    payload={"status": "retrying", "attempt": context.attempt},
                )
        if transitioned:
            await self._event_notifier.notify(context.run_id)
        return transitioned

    async def fail(
        self,
        context: NodeExecutionContext,
        error: JsonObject,
        *,
        review: ReviewResult | None = None,
        usage: JsonObject | None = None,
    ) -> bool:
        transitioned = False
        async with self._session_factory.begin() as session:
            transitioned = await RunRepository(session).fail_node(
                context.run_id,
                context.node_key,
                error,
                review.model_dump(mode="json") if review is not None else None,
                usage,
            )
            if transitioned:
                events = EventService(RunEventRepository(session))
                if review is not None:
                    await events.append(
                        context.run_id,
                        "node.reviewed",
                        node_key=context.node_key,
                        payload={"decision": review.decision, "score": review.score},
                    )
                if usage is not None:
                    await events.append(
                        context.run_id,
                        "llm.usage_recorded",
                        node_key=context.node_key,
                        payload=usage,
                    )
                await events.append(
                    context.run_id,
                    "node.failed",
                    node_key=context.node_key,
                    payload={
                        "status": "failed",
                        "attempt": context.attempt,
                        "code": error.get("code", "WORKER_FAILED"),
                    },
                )
        if transitioned:
            await self._event_notifier.notify(context.run_id)
        return transitioned


class Worker:
    """Run model/tool/reviewer turns without leaking node failures to siblings."""

    def __init__(
        self,
        store: WorkerStore,
        llm: LLMProvider,
        reviewer: DeterministicReviewer,
        tools: ToolRegistry,
        *,
        model: str,
        max_turns: int = 6,
        timeout_seconds: float = 60,
    ) -> None:
        self._store = store
        self._llm = llm
        self._reviewer = reviewer
        self._tools = tools
        self._model = model
        self._max_turns = max_turns
        self._timeout_seconds = timeout_seconds
        self._logger = structlog.get_logger(__name__)

    async def execute(self, run_id: UUID, node_key: str) -> None:
        """Execute bounded attempts and convert every node error to persisted state."""

        context = await self._store.load_context(run_id, node_key)
        if context is None:
            return
        try:
            while True:
                result = await self._execute_attempt(context)
                if result != "retry":
                    return
                next_context = await self._store.load_context(run_id, node_key)
                if next_context is None or next_context.attempt <= context.attempt:
                    return
                context = next_context
        except Exception as error:
            self._logger.exception(
                "worker_execution_failed",
                run_id=str(run_id),
                node_key=node_key,
                attempt=context.attempt,
            )
            try:
                await self._store.fail(
                    context,
                    {"code": "WORKER_EXECUTION_FAILED", "message": str(error)},
                )
            except Exception:
                self._logger.exception(
                    "worker_failure_persistence_failed",
                    run_id=str(run_id),
                    node_key=node_key,
                    attempt=context.attempt,
                )

    async def _execute_attempt(self, context: NodeExecutionContext) -> AttemptResult:
        messages = build_worker_messages(context)
        if not await self._store.start_attempt(context, messages):
            return "stale"

        input_tokens = 0
        output_tokens = 0
        response_model = self._model
        for _ in range(self._max_turns):
            response = await self._llm.complete(
                LLMRequest(
                    model=self._model,
                    messages=messages,
                    tools=self._tools.definitions(context.node.tools),
                    response_schema=context.node.output_schema,
                    timeout_seconds=self._timeout_seconds,
                )
            )
            input_tokens += response.input_tokens
            output_tokens += response.output_tokens
            response_model = response.model
            assistant = LLMMessage(
                role="assistant",
                content=response.content or _json_content(response.structured_output),
                tool_calls=response.tool_calls,
            )
            messages.append(assistant)
            await self._store.append_message(context.node_run_id, assistant)

            if response.tool_calls:
                await self._execute_tools(context, response.tool_calls, messages)
                continue

            if response.structured_output is not None:
                usage = _usage(response_model, input_tokens, output_tokens)
                if not await self._store.mark_reviewing(
                    context,
                    response.structured_output,
                    usage,
                ):
                    return "stale"
                review = self._reviewer.review(
                    response.structured_output,
                    context.node.output_schema,
                )
                reviewer_message = LLMMessage(
                    role="reviewer",
                    content=review.model_dump_json(),
                )
                messages.append(reviewer_message)
                await self._store.append_message(context.node_run_id, reviewer_message)
                if review.decision == "accept":
                    transitioned = await self._store.accept(
                        context,
                        response.structured_output,
                        review,
                    )
                    return "completed" if transitioned else "stale"
                if review.decision == "retry" and context.attempt <= context.max_retries:
                    transitioned = await self._store.retry(context, review)
                    return "retry" if transitioned else "stale"
                code = (
                    "REVIEW_RETRIES_EXHAUSTED" if review.decision == "retry" else "REVIEW_REJECTED"
                )
                await self._store.fail(
                    context,
                    {"code": code, "message": review.feedback},
                    review=review,
                    usage=usage,
                )
                return "failed"

        await self._store.fail(
            context,
            {
                "code": "MAX_TURNS_EXCEEDED",
                "message": f"Worker exceeded {self._max_turns} model turns",
            },
            usage=_usage(response_model, input_tokens, output_tokens),
        )
        return "failed"

    async def _execute_tools(
        self,
        context: NodeExecutionContext,
        tool_calls: Sequence[ToolCall],
        messages: list[LLMMessage],
    ) -> None:
        tool_context = ToolContext(
            task_context=context.task_context,
            upstream_outputs=context.upstream_outputs,
        )
        for tool_call in tool_calls:
            try:
                result = await self._tools.execute(
                    tool_call.name,
                    tool_call.arguments,
                    context.node.tools,
                    tool_context,
                )
            except ToolError as error:
                result = error.as_payload()
            tool_message = LLMMessage(
                role="tool",
                content=_json_content(result),
                tool_call_id=tool_call.id,
            )
            messages.append(tool_message)
            await self._store.append_message(context.node_run_id, tool_message)


def _usage(model: str, input_tokens: int, output_tokens: int) -> JsonObject:
    return {
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }


def _json_content(value: JsonValue | None) -> str:
    if value is None:
        return ""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _tool_call_payloads(tool_calls: Sequence[ToolCall]) -> list[dict[str, object]]:
    return [tool_call.model_dump(mode="json") for tool_call in tool_calls]


__all__ = ["DatabaseWorkerStore", "Worker", "WorkerStore"]
