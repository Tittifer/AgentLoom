"""Tests for planner and persisted workflow contracts."""

from typing import cast

import pytest
from pydantic import ValidationError

from agentloom.agents.schemas import WorkflowPlan


def valid_plan_payload() -> dict[str, object]:
    return {
        "nodes": [
            {
                "key": "research_product",
                "name": "Research product",
                "role": "researcher",
                "description": "Collect product facts",
                "system_prompt": "Return sourced product facts.",
                "depends_on": [],
                "tools": ["web_search"],
                "output_schema": {"type": "object"},
                "review_criteria": "Facts include sources.",
            }
        ],
        "final_node": "research_product",
    }


def test_workflow_plan_parses_valid_json() -> None:
    plan = WorkflowPlan.model_validate(valid_plan_payload())

    assert plan.final_node == "research_product"
    assert plan.nodes[0].tools == ["web_search"]


@pytest.mark.parametrize("missing_field", ["depends_on", "tools", "output_schema"])
def test_planned_node_requires_explicit_graph_fields(missing_field: str) -> None:
    payload = valid_plan_payload()
    nodes = cast(list[dict[str, object]], payload["nodes"])
    node = nodes[0]
    del node[missing_field]

    with pytest.raises(ValidationError) as error:
        WorkflowPlan.model_validate(payload)

    assert missing_field in str(error.value)


@pytest.mark.parametrize("key", ["Uppercase", "1starts_with_number", "contains-dash"])
def test_workflow_plan_rejects_invalid_node_keys(key: str) -> None:
    payload = valid_plan_payload()
    nodes = cast(list[dict[str, object]], payload["nodes"])
    node = nodes[0]
    node["key"] = key

    with pytest.raises(ValidationError):
        WorkflowPlan.model_validate(payload)
