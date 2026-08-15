"""Run and node-attempt persistence models."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy import (
    Enum as SqlEnum,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from agentloom.db.base import Base, JsonObject, enum_values, utc_now
from agentloom.runtime.states import NodeRunStatus, RunStatus

if TYPE_CHECKING:
    from agentloom.db.models.event import RunEventModel
    from agentloom.db.models.message import AgentMessageModel
    from agentloom.db.models.task import TaskModel
    from agentloom.db.models.workflow import WorkflowModel


class RunModel(Base):
    """One complete execution of a workflow."""

    __tablename__ = "runs"
    __table_args__ = (Index("ix_runs_status", "status"),)

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    task_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="RESTRICT"),
    )
    workflow_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("workflows.id", ondelete="RESTRICT"),
    )
    status: Mapped[RunStatus] = mapped_column(
        SqlEnum(
            RunStatus,
            name="run_status",
            values_callable=enum_values,
            validate_strings=True,
        ),
        default=RunStatus.QUEUED,
    )
    input: Mapped[JsonObject] = mapped_column(JSONB, default=dict)
    result: Mapped[JsonObject | None] = mapped_column(JSONB)
    error: Mapped[JsonObject | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    task: Mapped[TaskModel] = relationship("TaskModel", back_populates="runs")
    workflow: Mapped[WorkflowModel] = relationship("WorkflowModel", back_populates="runs")
    node_runs: Mapped[list[NodeRunModel]] = relationship(
        "NodeRunModel",
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    events: Mapped[list[RunEventModel]] = relationship(
        "RunEventModel",
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class NodeRunModel(Base):
    """One attempt to execute a workflow node within a run."""

    __tablename__ = "node_runs"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "node_key",
            "attempt",
            name="uq_node_runs_run_id_node_key_attempt",
        ),
        CheckConstraint("attempt > 0", name="attempt_positive"),
        Index("ix_node_runs_run_id_status", "run_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    run_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("runs.id", ondelete="CASCADE"),
    )
    node_key: Mapped[str] = mapped_column(String(100))
    status: Mapped[NodeRunStatus] = mapped_column(
        SqlEnum(
            NodeRunStatus,
            name="node_run_status",
            values_callable=enum_values,
            validate_strings=True,
        ),
        default=NodeRunStatus.PENDING,
    )
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    input: Mapped[JsonObject] = mapped_column(JSONB, default=dict)
    output: Mapped[JsonObject | None] = mapped_column(JSONB)
    review: Mapped[JsonObject | None] = mapped_column(JSONB)
    usage: Mapped[JsonObject | None] = mapped_column(JSONB)
    error: Mapped[JsonObject | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    run: Mapped[RunModel] = relationship("RunModel", back_populates="node_runs")
    messages: Mapped[list[AgentMessageModel]] = relationship(
        "AgentMessageModel",
        back_populates="node_run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
