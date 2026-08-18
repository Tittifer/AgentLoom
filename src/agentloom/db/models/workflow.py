"""Workflow graph persistence models."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from agentloom.db.base import Base, JsonObject, utc_now

if TYPE_CHECKING:
    from agentloom.db.models.run import RunModel
    from agentloom.db.models.task import TaskModel


class WorkflowModel(Base):
    """One version of a validated workflow for a task."""

    __tablename__ = "workflows"
    __table_args__ = (
        UniqueConstraint("task_id", "version", name="uq_workflows_task_id_version"),
        CheckConstraint("version > 0", name="version_positive"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    task_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="RESTRICT"),
    )
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32))
    final_node_key: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
    )

    task: Mapped[TaskModel] = relationship("TaskModel", back_populates="workflows")
    nodes: Mapped[list[WorkflowNodeModel]] = relationship(
        "WorkflowNodeModel",
        back_populates="workflow",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    edges: Mapped[list[WorkflowEdgeModel]] = relationship(
        "WorkflowEdgeModel",
        back_populates="workflow",
        cascade="all, delete-orphan",
        passive_deletes=True,
        foreign_keys="WorkflowEdgeModel.workflow_id",
    )
    runs: Mapped[list[RunModel]] = relationship(
        "RunModel",
        back_populates="workflow",
        passive_deletes=True,
    )


class WorkflowNodeModel(Base):
    """A single executable node in a workflow graph."""

    __tablename__ = "workflow_nodes"
    __table_args__ = (
        UniqueConstraint(
            "workflow_id",
            "node_key",
            name="uq_workflow_nodes_workflow_id_node_key",
        ),
        CheckConstraint("sort_order >= 0", name="sort_order_non_negative"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    workflow_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("workflows.id", ondelete="CASCADE"),
    )
    node_key: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text)
    prompt: Mapped[str] = mapped_column(Text)
    tools: Mapped[list[str]] = mapped_column(JSONB, default=list)
    output_schema: Mapped[JsonObject] = mapped_column(JSONB, default=dict)
    review_criteria: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    workflow: Mapped[WorkflowModel] = relationship("WorkflowModel", back_populates="nodes")


class WorkflowEdgeModel(Base):
    """A directed dependency between two nodes in the same workflow."""

    __tablename__ = "workflow_edges"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workflow_id", "source_node_key"],
            ["workflow_nodes.workflow_id", "workflow_nodes.node_key"],
            name="fk_workflow_edges_source_node",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workflow_id", "target_node_key"],
            ["workflow_nodes.workflow_id", "workflow_nodes.node_key"],
            name="fk_workflow_edges_target_node",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "workflow_id",
            "source_node_key",
            "target_node_key",
            name="uq_workflow_edges_workflow_source_target",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    workflow_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("workflows.id", ondelete="CASCADE"),
    )
    source_node_key: Mapped[str] = mapped_column(String(100))
    target_node_key: Mapped[str] = mapped_column(String(100))

    workflow: Mapped[WorkflowModel] = relationship(
        "WorkflowModel",
        back_populates="edges",
        foreign_keys=[workflow_id],
    )
