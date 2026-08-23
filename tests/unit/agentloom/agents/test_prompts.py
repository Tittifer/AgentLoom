"""Tests for bounded worker prompt construction."""

from uuid import uuid4

from agentloom.agents.prompts import MAX_PROMPT_SECTION_CHARS, build_worker_messages
from agentloom.runtime.run import NodeExecutionContext
from agentloom.runtime.workflow import WorkflowNodeRead


def test_worker_prompt_uses_only_direct_context_and_previous_feedback() -> None:
    context = NodeExecutionContext(
        run_id=uuid4(),
        node_run_id=uuid4(),
        node_key="write_report",
        attempt=2,
        task_goal="Compare products",
        task_context={"language": "en"},
        node=WorkflowNodeRead(
            id=uuid4(),
            key="write_report",
            name="Write report",
            role="writer",
            description="Create a report",
            system_prompt="Be concise",
            depends_on=["research"],
            tools=[],
            output_schema={"type": "object"},
            review_criteria="Include sources",
            sort_order=1,
        ),
        upstream_outputs={"research": {"summary": "facts"}},
        previous_feedback="Add a conclusion",
        max_retries=2,
    )

    messages = build_worker_messages(context)

    assert [message.role for message in messages] == ["system", "user"]
    assert "Output JSON Schema" in messages[0].content
    assert "Direct upstream results" in messages[1].content
    assert "Add a conclusion" in messages[1].content


def test_worker_prompt_truncates_large_json_sections() -> None:
    context = NodeExecutionContext.model_validate(
        {
            **_context_payload(),
            "task_context": {"large": "x" * (MAX_PROMPT_SECTION_CHARS + 100)},
        }
    )

    messages = build_worker_messages(context)

    assert "[TRUNCATED]" in messages[1].content


def _context_payload() -> dict[str, object]:
    return {
        "run_id": uuid4(),
        "node_run_id": uuid4(),
        "node_key": "node",
        "attempt": 1,
        "task_goal": "Goal",
        "task_context": {},
        "node": {
            "id": uuid4(),
            "key": "node",
            "name": "Node",
            "role": "worker",
            "description": "Work",
            "system_prompt": "Work",
            "depends_on": [],
            "tools": [],
            "output_schema": {"type": "object"},
            "review_criteria": None,
            "sort_order": 0,
        },
        "upstream_outputs": {},
        "previous_feedback": None,
        "max_retries": 1,
    }
