"""Static product-research workflow fixture."""

from pathlib import Path

from agentloom.agents.schemas import WorkflowPlan

PRODUCT_RESEARCH_TOOLS = frozenset({"web_search"})
WORKFLOW_PATH = (
    Path(__file__).resolve().parents[2] / "examples" / "product_research" / "expected_workflow.json"
)


def load_product_research_plan() -> WorkflowPlan:
    """Load and validate the checked-in static product-research workflow."""

    return WorkflowPlan.model_validate_json(WORKFLOW_PATH.read_text(encoding="utf-8"))


__all__ = ["PRODUCT_RESEARCH_TOOLS", "load_product_research_plan"]
