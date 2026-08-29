"""Persistent queen task-plan items."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from agentloom.db.base import Base, JsonObject, enum_values, utc_now
from agentloom.runtime.states import TaskItemStatus

if TYPE_CHECKING:
    from agentloom.db.models.colony import ColonyModel


class TaskItemModel(Base):
    """One durable item in the queen's editable plan."""

    __tablename__ = "task_items"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    colony_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("colonies.id", ondelete="CASCADE"),
        index=True,
    )
    session_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("agent_sessions.id", ondelete="CASCADE")
    )
    parent_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("task_items.id", ondelete="CASCADE"),
        nullable=True,
    )
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[TaskItemStatus] = mapped_column(
        SqlEnum(
            TaskItemStatus,
            name="task_item_status",
            values_callable=enum_values,
            validate_strings=True,
        ),
        default=TaskItemStatus.PENDING,
    )
    position: Mapped[int] = mapped_column(Integer, default=0)
    assigned_worker_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("worker_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    metadata_: Mapped[JsonObject] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    colony: Mapped[ColonyModel] = relationship("ColonyModel", back_populates="task_items")


__all__ = ["TaskItemModel"]
