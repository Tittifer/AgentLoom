"""Strict public and runtime contracts for Colony execution."""

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue

from agentloom.runtime.states import ColonyStatus, SessionStatus, TaskItemStatus, WorkerStatus

JsonObject = dict[str, JsonValue]
ActorType = Literal["queen", "worker"]
ReportStatus = Literal["success", "partial", "failed"]


class ColonyModel(BaseModel):
    """Strict base contract shared by Colony DTOs."""

    model_config = ConfigDict(extra="forbid", from_attributes=True, str_strip_whitespace=True)


class ColonyCreate(ColonyModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    queen_profile: str = Field(default="general", min_length=1, max_length=100)
    model: str | None = Field(default=None, min_length=1, max_length=200)
    settings: JsonObject = Field(default_factory=dict)


class ColonyRead(ColonyModel):
    id: UUID
    name: str
    description: str
    status: ColonyStatus
    queen_profile: str
    model: str
    settings: JsonObject
    queen_session_id: UUID | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime


class SessionRead(ColonyModel):
    id: UUID
    colony_id: UUID
    parent_session_id: UUID | None
    actor_type: ActorType
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
    tool_call_id: str | None
    tool_calls: list[JsonObject]
    metadata: JsonObject
    created_at: AwareDatetime


class WorkerTask(ColonyModel):
    task: str = Field(min_length=1)
    data: JsonObject = Field(default_factory=dict)


class WorkerRead(ColonyModel):
    id: UUID
    colony_id: UUID
    queen_session_id: UUID
    worker_session_id: UUID
    status: WorkerStatus
    task: str
    input: JsonObject
    report: JsonObject | None
    error: JsonObject | None
    timeout_seconds: int = Field(gt=0)
    queued_at: AwareDatetime
    started_at: AwareDatetime | None
    ended_at: AwareDatetime | None


class WorkerReport(ColonyModel):
    status: ReportStatus
    summary: str = Field(min_length=1)
    data: JsonObject = Field(default_factory=dict)


class TrackerUpsert(ColonyModel):
    namespace: str = Field(min_length=1, max_length=100)
    entry_key: str = Field(min_length=1, max_length=200)
    status: str = Field(default="pending", min_length=1, max_length=50)
    data: JsonObject = Field(default_factory=dict)
    expected_version: int | None = Field(default=None, ge=1)


class TrackerEntryRead(ColonyModel):
    id: UUID
    colony_id: UUID
    namespace: str
    entry_key: str
    status: str
    data: JsonObject
    version: int
    updated_by_session_id: UUID | None
    created_at: AwareDatetime
    updated_at: AwareDatetime


class TaskItemCreate(ColonyModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    parent_id: UUID | None = None
    position: int = Field(default=0, ge=0)
    metadata: JsonObject = Field(default_factory=dict)


class TaskItemUpdate(ColonyModel):
    status: TaskItemStatus


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
    colony_id: UUID
    session_id: UUID | None
    worker_run_id: UUID | None
    sequence: int = Field(gt=0)
    type: str
    payload: JsonObject
    created_at: AwareDatetime


class ColonySnapshot(ColonyModel):
    colony: ColonyRead
    queen_session: SessionRead
    workers: list[WorkerRead]
    tasks: list[TaskItemRead]
    tracker: list[TrackerEntryRead]


__all__ = [
    "ActorType",
    "ColonyCreate",
    "ColonyEventRead",
    "ColonyRead",
    "ColonySnapshot",
    "JsonObject",
    "MessageCreate",
    "MessageRead",
    "ReportStatus",
    "SessionRead",
    "TaskItemCreate",
    "TaskItemRead",
    "TaskItemUpdate",
    "TrackerEntryRead",
    "TrackerUpsert",
    "WorkerRead",
    "WorkerReport",
    "WorkerTask",
]
