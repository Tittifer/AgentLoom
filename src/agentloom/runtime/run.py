"""Run, node-attempt, event, and scheduler snapshot DTOs."""

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue

from agentloom.runtime.states import NodeRunStatus, RunStatus
from agentloom.runtime.workflow import WorkflowRead

JsonPayload = dict[str, JsonValue]
RunEventType = Literal[
    "run.started",
    "run.completed",
    "run.failed",
    "node.started",
    "node.reviewed",
    "node.retrying",
    "node.completed",
    "node.failed",
]


class RunDto(BaseModel):
    """Base model for strict run data crossing runtime boundaries."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class RunRead(RunDto):
    """Stored state of one complete workflow execution."""

    id: UUID
    task_id: UUID
    workflow_id: UUID
    status: RunStatus
    input: JsonPayload
    result: JsonPayload | None
    error: JsonPayload | None
    created_at: AwareDatetime
    started_at: AwareDatetime | None
    ended_at: AwareDatetime | None


class NodeRunRead(RunDto):
    """Latest persisted attempt for one workflow node."""

    id: UUID
    run_id: UUID
    node_key: str = Field(min_length=1)
    status: NodeRunStatus
    attempt: int = Field(ge=1)
    input: JsonPayload
    output: JsonPayload | None
    review: JsonPayload | None
    usage: JsonPayload | None
    error: JsonPayload | None
    created_at: AwareDatetime
    started_at: AwareDatetime | None
    ended_at: AwareDatetime | None


class AgentMessageRead(RunDto):
    """One model-visible message associated with a node attempt."""

    id: UUID
    node_run_id: UUID
    role: str = Field(min_length=1)
    content: str
    tool_calls: list[JsonPayload]
    created_at: AwareDatetime


class RunEventRead(RunDto):
    """One ordered event emitted while a workflow run advances."""

    id: UUID
    run_id: UUID
    sequence: int = Field(ge=1)
    type: RunEventType
    node_key: str | None
    payload: JsonPayload
    created_at: AwareDatetime


class RunSnapshot(RunDto):
    """Complete scheduler and run-detail view loaded through one repository call."""

    run: RunRead
    workflow: WorkflowRead
    node_runs: list[NodeRunRead]
    upstream_outputs: dict[str, dict[str, JsonPayload]]
    current_running_nodes: int = Field(ge=0)
    max_parallel_nodes: int = Field(ge=1)

    @property
    def is_terminal(self) -> bool:
        return self.run.status in {
            RunStatus.COMPLETED,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
        }

    @property
    def has_running_nodes(self) -> bool:
        return self.current_running_nodes > 0


__all__ = [
    "AgentMessageRead",
    "JsonPayload",
    "NodeRunRead",
    "RunEventRead",
    "RunEventType",
    "RunRead",
    "RunSnapshot",
]
