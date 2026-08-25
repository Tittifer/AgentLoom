"""Bounded, deterministic message construction for AgentLoom agents."""

import json
from collections.abc import Sequence

from pydantic import JsonValue

from agentloom.llm.base import LLMMessage, ToolDefinition
from agentloom.runtime.run import NodeExecutionContext

MAX_PROMPT_SECTION_CHARS = 20_000


def build_planner_messages(
    goal: str,
    context: dict[str, JsonValue],
    agent_roles: Sequence[str],
    tools: Sequence[ToolDefinition],
    *,
    max_nodes: int,
    max_parallel_nodes: int,
    max_retries: int,
) -> list[LLMMessage]:
    """Build the fixed planner context without executing any task work."""

    system_sections = [
        "You are the AgentLoom planner. Decompose the task into a valid executable DAG.",
        "Plan only: do not execute the task and do not call tools.",
        "Use only the listed agent roles and tools.",
        "Every dependency must reference a node key in the same plan.",
        "The final node must exist and have no downstream nodes.",
        f"Maximum nodes: {max_nodes}",
        f"Runtime parallel-node limit: {max_parallel_nodes}",
        f"Runtime retries per node: {max_retries}",
        f"Available agent roles: {_bounded_json(list(agent_roles))}",
        "Available read-only tools: "
        + _bounded_json([tool.model_dump(mode="json") for tool in tools]),
    ]
    user_sections = [
        f"Task goal: {goal}",
        f"Task context: {_bounded_json(context)}",
        "Return only a WorkflowPlan matching the required JSON Schema.",
    ]
    return [
        LLMMessage(role="system", content="\n".join(system_sections)),
        LLMMessage(role="user", content="\n".join(user_sections)),
    ]


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


__all__ = [
    "MAX_PROMPT_SECTION_CHARS",
    "build_planner_messages",
    "build_worker_messages",
]
