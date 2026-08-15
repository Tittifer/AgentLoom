"""Task persistence model."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import DateTime, String, Text
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from agentloom.db.base import Base, JsonObject, enum_values, utc_now
from agentloom.runtime.states import TaskStatus

if TYPE_CHECKING:
    from agentloom.db.models.run import RunModel
    from agentloom.db.models.workflow import WorkflowModel


def default_task_settings() -> JsonObject:
    """Return independent default execution settings for a task."""

    return {"max_parallel_nodes": 3, "max_retries": 2}


class TaskModel(Base):
    """A user goal and its execution limits."""

    __tablename__ = "tasks"

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    title: Mapped[str] = mapped_column(String(200))
    goal: Mapped[str] = mapped_column(Text)
    context: Mapped[JsonObject] = mapped_column(JSONB, default=dict)
    status: Mapped[TaskStatus] = mapped_column(
        SqlEnum(
            TaskStatus,
            name="task_status",
            values_callable=enum_values,
            validate_strings=True,
        ),
        default=TaskStatus.DRAFT,
    )
    settings: Mapped[JsonObject] = mapped_column(JSONB, default=default_task_settings)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
    )

    workflows: Mapped[list[WorkflowModel]] = relationship(
        "WorkflowModel",
        back_populates="task",
        passive_deletes=True,
    )
    runs: Mapped[list[RunModel]] = relationship(
        "RunModel",
        back_populates="task",
        passive_deletes=True,
    )
