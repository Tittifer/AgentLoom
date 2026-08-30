"""Long-lived colony persistence model."""

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
from agentloom.runtime.states import ColonyStatus

if TYPE_CHECKING:
    from agentloom.db.models.artifact import ArtifactModel
    from agentloom.db.models.colony_event import ColonyEventModel
    from agentloom.db.models.session import AgentSessionModel
    from agentloom.db.models.task_item import TaskItemModel
    from agentloom.db.models.tracker import TrackerEntryModel
    from agentloom.db.models.worker import WorkerRunModel


def default_colony_settings() -> JsonObject:
    """Return independent, bounded colony defaults."""

    return {
        "max_concurrent_workers": 4,
        "worker_max_turns": 8,
        "worker_timeout_seconds": 600,
        "max_tool_calls": 20,
    }


class ColonyModel(Base):
    """A persistent queen, its workers, plan, and shared ledger."""

    __tablename__ = "colonies"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[ColonyStatus] = mapped_column(
        SqlEnum(
            ColonyStatus,
            name="colony_status",
            values_callable=enum_values,
            validate_strings=True,
        ),
        default=ColonyStatus.ACTIVE,
        index=True,
    )
    queen_profile: Mapped[str] = mapped_column(String(100), default="general")
    model: Mapped[str] = mapped_column(String(200))
    settings: Mapped[JsonObject] = mapped_column(JSONB, default=default_colony_settings)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    sessions: Mapped[list[AgentSessionModel]] = relationship(
        "AgentSessionModel", back_populates="colony", passive_deletes=True
    )
    workers: Mapped[list[WorkerRunModel]] = relationship(
        "WorkerRunModel", back_populates="colony", passive_deletes=True
    )
    tracker_entries: Mapped[list[TrackerEntryModel]] = relationship(
        "TrackerEntryModel", back_populates="colony", passive_deletes=True
    )
    task_items: Mapped[list[TaskItemModel]] = relationship(
        "TaskItemModel", back_populates="colony", passive_deletes=True
    )
    artifacts: Mapped[list[ArtifactModel]] = relationship(
        "ArtifactModel", back_populates="colony", passive_deletes=True
    )
    events: Mapped[list[ColonyEventModel]] = relationship(
        "ColonyEventModel", back_populates="colony", passive_deletes=True
    )


__all__ = ["ColonyModel", "default_colony_settings"]
