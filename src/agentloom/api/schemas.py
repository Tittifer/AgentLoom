"""Public API data transfer objects."""

from typing import Generic, TypeVar
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue

from agentloom.runtime.states import TaskStatus


class ApiModel(BaseModel):
    """Base model for strict, ORM-compatible public API contracts."""

    model_config = ConfigDict(
        extra="forbid",
        from_attributes=True,
        str_strip_whitespace=True,
    )


class HealthResponse(ApiModel):
    """Response returned by the health endpoint."""

    status: str


class TaskSettings(ApiModel):
    """Limits controlling the execution of a task workflow."""

    max_parallel_nodes: int = Field(default=3, ge=1, le=20)
    max_retries: int = Field(default=2, ge=0)


class TaskCreate(TaskSettings):
    """Payload accepted when a user creates a task."""

    title: str = Field(min_length=1, max_length=200)
    goal: str = Field(min_length=1)
    context: dict[str, JsonValue] = Field(default_factory=dict)


class TaskRead(TaskCreate):
    """Task representation returned by the API."""

    id: UUID
    status: TaskStatus
    created_at: AwareDatetime


class ApiErrorDetail(ApiModel):
    """Location and reason for one API validation or domain error."""

    path: str
    reason: str


class ApiError(ApiModel):
    """Consistent error response returned by API endpoints."""

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    details: list[ApiErrorDetail] = Field(
        default_factory=lambda: list[ApiErrorDetail](),
    )


ItemT = TypeVar("ItemT")


class PaginatedResponse(ApiModel, Generic[ItemT]):
    """Metadata and resources returned by paginated list endpoints."""

    items: list[ItemT]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    total: int = Field(ge=0)


__all__ = [
    "ApiError",
    "ApiErrorDetail",
    "HealthResponse",
    "PaginatedResponse",
    "TaskCreate",
    "TaskRead",
    "TaskSettings",
]
