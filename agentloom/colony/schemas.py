"""Strict public and runtime contracts for Colony execution."""

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue

from agentloom.llm.base import ReasoningContent
from agentloom.runtime.states import ColonyStatus, SessionStatus, TaskItemStatus, WorkerStatus

JsonObject = dict[str, JsonValue]
ActorType = Literal["queen", "worker"]
SessionMode = Literal["dm", "colony"]
ReportStatus = Literal["success", "partial", "failed"]
PlaybookRunStatus = Literal["queued", "running", "completed", "blocked", "cancelled"]
DEFAULT_WORKER_MAX_ITERATIONS = 3
DEFAULT_WORKER_GRACE_ITERATIONS = 1
DEFAULT_WORKER_TOOL_CALL_BUDGET = 30
WORKER_TOOL_CALL_HARD_MULTIPLE = 3
DEFAULT_WORKER_TOOL_CALL_LIFETIME_BUDGET = 200


def _empty_uuid_list() -> list[UUID]:
    return []


def _empty_json_object_list() -> list[JsonObject]:
    return []


class ColonyModel(BaseModel):
    """Strict base contract shared by Colony DTOs."""

    model_config = ConfigDict(extra="forbid", from_attributes=True, str_strip_whitespace=True)


class QueenProfile(ColonyModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=1_000)
    system_prompt: str = Field(default="", max_length=20_000)


class QueenCreate(QueenProfile):
    pass


class QueenRead(QueenProfile):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,99}$")
    created_at: AwareDatetime
    updated_at: AwareDatetime


class ColonyCreate(ColonyModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    queen_id: str = Field(min_length=1, max_length=100)
    settings: JsonObject = Field(default_factory=dict)


class ColonyRead(ColonyModel):
    layout_version: Literal[2] = 2
    id: UUID
    name: str
    description: str
    status: ColonyStatus
    queen_id: str
    model: str
    settings: JsonObject
    source_session_id: UUID | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime


class ColonySuggestion(ColonyModel):
    id: UUID
    suggested_name: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=2_000)
    goal: str = Field(min_length=1, max_length=4_000)
    handoff: str = Field(min_length=1, max_length=20_000)
    proposed_tasks: list[str] = Field(default_factory=list, max_length=100)
    status: Literal["pending", "accepted", "dismissed"] = "pending"
    created_at: AwareDatetime


class ColonyForkCreate(ColonyModel):
    suggestion_id: UUID
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2_000)


class SessionCreate(ColonyModel):
    queen_id: str = Field(min_length=1, max_length=100)
    colony_id: UUID | None = None
    source_session_id: UUID | None = None


class SessionRead(ColonyModel):
    layout_version: Literal[2] = 2
    id: UUID
    colony_id: UUID | None = None
    queen_id: str
    mode: SessionMode = "dm"
    pending_colony_suggestion: ColonySuggestion | None = None
    spawned_colony_id: UUID | None = None
    superseded_by: UUID | None = None
    status: SessionStatus
    park_reason: str | None
    task: JsonObject
    cursor: JsonObject
    budget: JsonObject
    usage: JsonObject
    created_at: AwareDatetime
    updated_at: AwareDatetime
    ended_at: AwareDatetime | None


class MessageCreate(ColonyModel):
    content: str = Field(min_length=1, max_length=100_000)


class MessageRead(ColonyModel):
    id: UUID
    session_id: UUID
    sequence: int = Field(gt=0)
    role: str
    content: str
    reasoning_content: ReasoningContent | None = Field(default=None, exclude=True, repr=False)
    tool_call_id: str | None
    tool_calls: list[JsonObject]
    metadata: JsonObject
    created_at: AwareDatetime


class WorkerTask(ColonyModel):
    task: str = Field(min_length=1)
    data: JsonObject = Field(
        default_factory=dict,
        description="Worker 输入；run_worker 调度时必须包含 task_id（task_create 返回的 UUID）",
    )


class WorkerRead(ColonyModel):
    layout_version: Literal[2] = 2
    id: UUID
    colony_id: UUID
    owner_session_id: UUID
    queen_id: str
    status: WorkerStatus
    park_reason: str | None = None
    task: str
    input: JsonObject
    cursor: JsonObject
    budget: JsonObject
    usage: JsonObject
    report: JsonObject | None
    error: JsonObject | None
    timeout_seconds: int = Field(gt=0)
    queued_at: AwareDatetime
    started_at: AwareDatetime | None
    updated_at: AwareDatetime
    ended_at: AwareDatetime | None


class AgentExecutionRead(ColonyModel):
    """Internal AgentLoop state; workers are executions, never public sessions."""

    id: UUID
    actor_type: ActorType
    colony_id: UUID | None = None
    queen_id: str
    owner_session_id: UUID
    mode: SessionMode
    status: SessionStatus | WorkerStatus
    park_reason: str | None
    task: JsonObject
    cursor: JsonObject
    budget: JsonObject
    usage: JsonObject
    created_at: AwareDatetime
    updated_at: AwareDatetime
    ended_at: AwareDatetime | None


class WorkerReport(ColonyModel):
    status: ReportStatus
    summary: str = Field(min_length=1)
    data: JsonObject = Field(default_factory=dict)


class TrackerUpsert(ColonyModel):
    table: str = Field(min_length=1, max_length=100)
    row: JsonObject = Field(min_length=1)


class TrackerColumnRead(ColonyModel):
    name: str
    type: str
    notnull: bool
    primary_key_position: int = Field(ge=0)
    default: JsonValue | None = None


class TrackerTableRead(ColonyModel):
    name: str
    columns: list[TrackerColumnRead]
    row_count: int = Field(ge=0)
    primary_key: list[str]


class TrackerRowsRead(ColonyModel):
    table: str
    columns: list[TrackerColumnRead]
    primary_key: list[str]
    rows: list[JsonObject]
    total: int = Field(ge=0)
    limit: int = Field(gt=0)
    offset: int = Field(ge=0)


class TrackerChangeRead(ColonyModel):
    id: int = Field(gt=0)
    table: str
    primary_key: JsonObject
    operation: Literal["insert", "update", "delete"]
    changed_at: str


class TrackerChangesRead(ColonyModel):
    changes: list[TrackerChangeRead]
    cursor: int = Field(ge=0)


class WorkerSkillRead(ColonyModel):
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,99}$")
    body: str = Field(min_length=1, max_length=50_000)
    updated_at: AwareDatetime


class PlaybookDefinition(ColonyModel):
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,99}$")
    task_id: UUID
    table: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,99}$")
    pending_sql: str = Field(min_length=1, max_length=20_000)
    key_columns: list[str] = Field(min_length=1, max_length=20)
    skill_name: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,99}$")
    task_template: str = Field(min_length=1, max_length=4_000)
    concurrency: int = Field(default=4, ge=1, le=16)
    max_rounds: int = Field(default=3, ge=1, le=10)
    worker_timeout_seconds: int = Field(default=600, ge=1, le=3_600)


class PlaybookRunRead(ColonyModel):
    id: UUID
    colony_id: UUID
    session_id: UUID
    definition: PlaybookDefinition
    status: PlaybookRunStatus
    round: int = Field(default=0, ge=0)
    worker_ids: list[UUID] = Field(default_factory=_empty_uuid_list)
    total_rows: int = Field(default=0, ge=0)
    completed_rows: int = Field(default=0, ge=0)
    remaining_rows: int = Field(default=0, ge=0)
    dead_letter: list[JsonObject] = Field(default_factory=_empty_json_object_list)
    error: str | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime


class TaskItemCreate(ColonyModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    parent_id: UUID | None = None
    position: int = Field(default=0, ge=0)
    metadata: JsonObject = Field(default_factory=dict)


class TaskItemRead(ColonyModel):
    id: UUID
    colony_id: UUID
    session_id: UUID
    parent_id: UUID | None
    title: str
    description: str
    status: TaskItemStatus
    position: int
    assigned_worker_id: UUID | None
    metadata: JsonObject
    created_at: AwareDatetime
    updated_at: AwareDatetime


class ColonyEventRead(ColonyModel):
    id: UUID
    colony_id: UUID | None = None
    session_id: UUID | None
    worker_run_id: UUID | None
    sequence: int = Field(gt=0)
    type: str
    payload: JsonObject
    created_at: AwareDatetime


class ColonySnapshot(ColonyModel):
    colony: ColonyRead
    session: SessionRead
    workers: list[WorkerRead]
    tasks: list[TaskItemRead]


__all__ = [
    "ActorType",
    "AgentExecutionRead",
    "ColonyCreate",
    "ColonyEventRead",
    "ColonyForkCreate",
    "ColonyRead",
    "ColonySuggestion",
    "ColonySnapshot",
    "DEFAULT_WORKER_GRACE_ITERATIONS",
    "DEFAULT_WORKER_MAX_ITERATIONS",
    "DEFAULT_WORKER_TOOL_CALL_BUDGET",
    "DEFAULT_WORKER_TOOL_CALL_LIFETIME_BUDGET",
    "JsonObject",
    "MessageCreate",
    "MessageRead",
    "PlaybookDefinition",
    "PlaybookRunRead",
    "PlaybookRunStatus",
    "QueenCreate",
    "QueenRead",
    "ReportStatus",
    "SessionCreate",
    "SessionMode",
    "SessionRead",
    "TaskItemCreate",
    "TaskItemRead",
    "TrackerColumnRead",
    "TrackerChangeRead",
    "TrackerChangesRead",
    "TrackerRowsRead",
    "TrackerTableRead",
    "TrackerUpsert",
    "WorkerRead",
    "WorkerReport",
    "WorkerSkillRead",
    "WorkerTask",
    "WORKER_TOOL_CALL_HARD_MULTIPLE",
]
