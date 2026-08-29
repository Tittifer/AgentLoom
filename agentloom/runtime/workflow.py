"""Public workflow graph representations."""

from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue

from agentloom.agents.schemas import NodeKey


class WorkflowDto(BaseModel):
    """Base model for strict workflow data returned by persistence."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class WorkflowNodeRead(WorkflowDto):
    """Stored definition of one workflow node."""

    id: UUID
    key: NodeKey
    name: str = Field(min_length=1, max_length=200)
    role: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1)
    system_prompt: str = Field(min_length=1)
    depends_on: list[NodeKey]
    tools: list[str]
    output_schema: dict[str, JsonValue]
    review_criteria: str | None = Field(default=None, min_length=1)
    sort_order: int = Field(ge=0)


class WorkflowEdgeRead(WorkflowDto):
    """Stored directed edge between two workflow nodes."""

    id: UUID
    source_node_key: NodeKey
    target_node_key: NodeKey


class WorkflowRead(WorkflowDto):
    """A complete persisted workflow graph."""

    id: UUID
    task_id: UUID
    version: int = Field(ge=1)
    status: str = Field(min_length=1)
    final_node: NodeKey
    created_at: AwareDatetime
    nodes: list[WorkflowNodeRead]
    edges: list[WorkflowEdgeRead]


__all__ = ["WorkflowEdgeRead", "WorkflowNodeRead", "WorkflowRead"]
