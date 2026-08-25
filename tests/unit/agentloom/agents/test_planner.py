"""Tests for bounded Planner generation and deterministic repair."""

from copy import deepcopy

import pytest

from agentloom.agents.planner import (
    Planner,
    PlannerGenerationError,
    PlannerProviderError,
)
from agentloom.llm.base import LLMProvider, LLMProviderError, LLMResponse
from agentloom.llm.mock import SchemaMockLLMProvider, ScriptedMockLLMProvider
from agentloom.tools.registry import create_builtin_tool_registry
from tests.fixtures.product_research import load_product_research_plan


def response(payload: dict[str, object]) -> LLMResponse:
    return LLMResponse.model_validate(
        {
            "model": "mock/planner",
            "structured_output": payload,
        }
    )


def create_planner(provider: LLMProvider, *, max_repairs: int = 2) -> Planner:
    registry = create_builtin_tool_registry()
    return Planner(
        provider,
        registry.definitions(),
        model="mock/planner",
        max_repairs=max_repairs,
    )


async def test_planner_accepts_a_valid_workflow_on_the_first_attempt() -> None:
    expected = load_product_research_plan()
    provider = ScriptedMockLLMProvider([response(expected.model_dump(mode="json"))])

    plan = await create_planner(provider).plan(
        "Compare Apple, Huawei, and Xiaomi",
        {"language": "en"},
        max_parallel_nodes=3,
        max_retries=2,
    )

    assert plan == expected
    assert len(provider.requests) == 1
    assert provider.requests[0].tools == []
    assert provider.requests[0].response_schema is not None


async def test_planner_repairs_invalid_dag_with_structured_feedback() -> None:
    valid_payload = load_product_research_plan().model_dump(mode="json")
    invalid_payload = deepcopy(valid_payload)
    invalid_payload["nodes"][0]["tools"] = ["shell"]
    provider = ScriptedMockLLMProvider([response(invalid_payload), response(valid_payload)])

    plan = await create_planner(provider).plan(
        "Compare products",
        {},
        max_parallel_nodes=3,
        max_retries=1,
    )

    assert plan.final_node == "write_report"
    assert len(provider.requests) == 2
    repair_request = provider.requests[1]
    assert [message.role for message in repair_request.messages[-2:]] == [
        "assistant",
        "user",
    ]
    assert "nodes.0.tools.0" in repair_request.messages[-1].content


async def test_planner_fails_after_two_repairs() -> None:
    invalid: dict[str, object] = {
        "nodes": list[object](),
        "final_node": "missing",
    }
    provider = ScriptedMockLLMProvider([response(invalid) for _ in range(3)])

    with pytest.raises(PlannerGenerationError) as error:
        await create_planner(provider).plan(
            "Impossible plan",
            {},
            max_parallel_nodes=1,
            max_retries=0,
        )

    assert len(provider.requests) == 3
    assert error.value.issues
    assert any(issue.path == "nodes" for issue in error.value.issues)


async def test_planner_converts_provider_errors() -> None:
    provider = ScriptedMockLLMProvider([LLMProviderError("provider unavailable")])

    with pytest.raises(PlannerProviderError) as error:
        await create_planner(provider).plan(
            "Compare products",
            {},
            max_parallel_nodes=3,
            max_retries=2,
        )

    assert str(error.value) == "Planner model request failed"


async def test_schema_mock_generates_the_four_node_mvp_workflow() -> None:
    provider = SchemaMockLLMProvider()

    plan = await create_planner(provider).plan(
        "Compare three products",
        {},
        max_parallel_nodes=3,
        max_retries=2,
    )

    assert [node.key for node in plan.nodes] == [
        "research_a",
        "research_b",
        "research_c",
        "write_report",
    ]
    assert plan.nodes[-1].depends_on == ["research_a", "research_b", "research_c"]
