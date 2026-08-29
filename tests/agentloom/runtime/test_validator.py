"""Tests for deterministic workflow graph validation."""

from copy import deepcopy
from typing import cast

from agentloom.agents.schemas import WorkflowPlan
from agentloom.runtime.validator import validate_workflow

REGISTERED_TOOLS = {"web_search", "read_task_context"}


def node(
    key: str,
    depends_on: list[str] | None = None,
    tools: list[str] | None = None,
) -> dict[str, object]:
    return {
        "key": key,
        "name": key.replace("_", " ").title(),
        "role": "researcher",
        "description": f"Complete {key}",
        "system_prompt": f"Complete the {key} node.",
        "depends_on": depends_on or [],
        "tools": tools or [],
        "output_schema": {"type": "object"},
        "review_criteria": None,
    }


def valid_plan_payload() -> dict[str, object]:
    return {
        "nodes": [
            node("research_a", tools=["web_search"]),
            node("research_b", tools=["web_search"]),
            node("write_report", depends_on=["research_a", "research_b"]),
        ],
        "final_node": "write_report",
    }


def error_codes(payload: dict[str, object]) -> list[str]:
    plan = WorkflowPlan.model_validate(payload)
    return [error.code for error in validate_workflow(plan, REGISTERED_TOOLS)]


def test_valid_dag_has_no_errors() -> None:
    assert error_codes(valid_plan_payload()) == []


def test_validator_reports_duplicate_and_missing_dependencies_together() -> None:
    payload = valid_plan_payload()
    nodes = cast(list[dict[str, object]], payload["nodes"])
    nodes.append(node("research_a", depends_on=["missing_node"]))

    codes = error_codes(payload)

    assert codes.count("duplicate_node_key") == 2
    assert "missing_dependency" in codes


def test_validator_reports_self_dependency_and_cycle() -> None:
    payload: dict[str, object] = {
        "nodes": [
            node("node_a", depends_on=["node_a", "node_b"]),
            node("node_b", depends_on=["node_a"]),
        ],
        "final_node": "node_b",
    }

    codes = error_codes(payload)

    assert "self_dependency" in codes
    assert "cycle_detected" in codes


def test_validator_reports_invalid_final_nodes() -> None:
    missing_final = valid_plan_payload()
    missing_final["final_node"] = "missing_node"
    non_terminal_final = valid_plan_payload()
    non_terminal_final["final_node"] = "research_a"

    assert "final_node_not_found" in error_codes(missing_final)
    assert "final_node_has_downstream" in error_codes(non_terminal_final)


def test_validator_reports_unregistered_tools_with_precise_path() -> None:
    payload = deepcopy(valid_plan_payload())
    nodes = cast(list[dict[str, object]], payload["nodes"])
    first_node = nodes[0]
    first_node["tools"] = ["shell"]
    plan = WorkflowPlan.model_validate(payload)

    errors = validate_workflow(plan, REGISTERED_TOOLS)

    assert [error.code for error in errors] == ["tool_not_registered"]
    assert errors[0].path == "nodes.0.tools.0"
