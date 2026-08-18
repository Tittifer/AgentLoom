"""Structured contracts produced by planner agents."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, JsonValue

NodeKey = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]


class AgentSchema(BaseModel):
    """Base class for strict structured agent output."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class PlannedNode(AgentSchema):
    """One node proposed by the planner."""

    key: NodeKey
    name: str = Field(min_length=1, max_length=200)
    role: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1)
    system_prompt: str = Field(min_length=1)
    depends_on: list[NodeKey]
    tools: list[str]
    output_schema: dict[str, JsonValue]
    review_criteria: str | None = Field(default=None, min_length=1)


class WorkflowPlan(AgentSchema):
    """A bounded workflow graph proposed by the planner."""

    nodes: list[PlannedNode] = Field(min_length=1, max_length=20)
    final_node: NodeKey


__all__ = ["NodeKey", "PlannedNode", "WorkflowPlan"]
