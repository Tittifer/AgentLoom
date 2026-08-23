"""Bounded, deterministic message construction for workers."""

import json

from agentloom.llm.base import LLMMessage
from agentloom.runtime.run import NodeExecutionContext

MAX_PROMPT_SECTION_CHARS = 20_000


def build_worker_messages(context: NodeExecutionContext) -> list[LLMMessage]:
    """Build the fixed worker context order without unrelated run history."""

    node = context.node
    system_sections = [
        "You are an AgentLoom worker. Follow the node objective and return only visible work.",
        "Never call a tool that is not explicitly listed for this node.",
        f"Role: {node.role}",
        f"Node objective: {node.description}",
        f"Node instructions: {node.system_prompt}",
        f"Output JSON Schema: {_bounded_json(node.output_schema)}",
        f"Reviewer criteria: {node.review_criteria or 'No additional criteria.'}",
    ]
    user_sections = [
        f"Task goal: {context.task_goal}",
        f"Task context: {_bounded_json(context.task_context)}",
        f"Direct upstream results: {_bounded_json(context.upstream_outputs)}",
    ]
    if context.previous_feedback is not None:
        user_sections.append(f"Previous reviewer feedback: {context.previous_feedback}")
    return [
        LLMMessage(role="system", content="\n".join(system_sections)),
        LLMMessage(role="user", content="\n".join(user_sections)),
    ]


def _bounded_json(value: object) -> str:
    serialized = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if len(serialized) <= MAX_PROMPT_SECTION_CHARS:
        return serialized
    return serialized[:MAX_PROMPT_SECTION_CHARS] + "[TRUNCATED]"


__all__ = ["MAX_PROMPT_SECTION_CHARS", "build_worker_messages"]
