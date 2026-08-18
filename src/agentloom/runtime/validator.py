"""Deterministic validation for planned workflow graphs."""

from collections import Counter, deque
from collections.abc import Collection
from typing import Literal

from pydantic import BaseModel, ConfigDict

from agentloom.agents.schemas import WorkflowPlan

WorkflowValidationCode = Literal[
    "duplicate_node_key",
    "missing_dependency",
    "self_dependency",
    "cycle_detected",
    "final_node_not_found",
    "final_node_has_downstream",
    "tool_not_registered",
]


class WorkflowValidationError(BaseModel):
    """One precisely located workflow validation problem."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: WorkflowValidationCode
    path: str
    message: str


def validate_workflow(
    plan: WorkflowPlan,
    registered_tools: Collection[str],
) -> list[WorkflowValidationError]:
    """Return all graph and tool errors in a planned workflow."""

    errors: list[WorkflowValidationError] = []
    key_counts = Counter(node.key for node in plan.nodes)
    node_keys = set(key_counts)
    registered_tool_names = set(registered_tools)

    adjacency: dict[str, set[str]] = {key: set() for key in node_keys}
    indegree: dict[str, int] = dict.fromkeys(node_keys, 0)

    for node_index, node in enumerate(plan.nodes):
        if key_counts[node.key] > 1:
            errors.append(
                WorkflowValidationError(
                    code="duplicate_node_key",
                    path=f"nodes.{node_index}.key",
                    message=f"Node key '{node.key}' is duplicated",
                )
            )

        for dependency_index, dependency in enumerate(node.depends_on):
            dependency_path = f"nodes.{node_index}.depends_on.{dependency_index}"
            if dependency == node.key:
                errors.append(
                    WorkflowValidationError(
                        code="self_dependency",
                        path=dependency_path,
                        message=f"Node '{node.key}' cannot depend on itself",
                    )
                )
                continue
            if dependency not in node_keys:
                errors.append(
                    WorkflowValidationError(
                        code="missing_dependency",
                        path=dependency_path,
                        message=f"Dependency '{dependency}' does not exist",
                    )
                )
                continue
            if node.key not in adjacency[dependency]:
                adjacency[dependency].add(node.key)
                indegree[node.key] += 1

        for tool_index, tool in enumerate(node.tools):
            if tool not in registered_tool_names:
                errors.append(
                    WorkflowValidationError(
                        code="tool_not_registered",
                        path=f"nodes.{node_index}.tools.{tool_index}",
                        message=f"Tool '{tool}' is not registered",
                    )
                )

    ready = deque(sorted(key for key, degree in indegree.items() if degree == 0))
    visited_count = 0
    while ready:
        key = ready.popleft()
        visited_count += 1
        for downstream in sorted(adjacency[key]):
            indegree[downstream] -= 1
            if indegree[downstream] == 0:
                ready.append(downstream)

    if visited_count != len(node_keys):
        errors.append(
            WorkflowValidationError(
                code="cycle_detected",
                path="nodes",
                message="Workflow contains a dependency cycle",
            )
        )

    if plan.final_node not in node_keys:
        errors.append(
            WorkflowValidationError(
                code="final_node_not_found",
                path="final_node",
                message=f"Final node '{plan.final_node}' does not exist",
            )
        )
    elif adjacency[plan.final_node]:
        errors.append(
            WorkflowValidationError(
                code="final_node_has_downstream",
                path="final_node",
                message=f"Final node '{plan.final_node}' must not have downstream nodes",
            )
        )

    return errors


__all__ = ["WorkflowValidationError", "validate_workflow"]
