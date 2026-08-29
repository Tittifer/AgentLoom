"""Dynamic colony worker persistence."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Text
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from agentloom.db.base import Base, JsonObject, enum_values, utc_now
from agentloom.runtime.states import WorkerStatus

if TYPE_CHECKING:
    from agentloom.db.models.colony import ColonyModel


class WorkerRunModel(Base):
    """One queued or active worker cloned from a queen session."""

    __tablename__ = "worker_runs"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    colony_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("colonies.id", ondelete="CASCADE"),
        index=True,
    )
    queen_session_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("agent_sessions.id", ondelete="CASCADE"),
    )
    worker_session_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("agent_sessions.id", ondelete="CASCADE"),
        unique=True,
    )
    status: Mapped[WorkerStatus] = mapped_column(
        SqlEnum(
            WorkerStatus,
            name="worker_status",
            values_callable=enum_values,
            validate_strings=True,
        ),
        default=WorkerStatus.QUEUED,
        index=True,
    )
    task: Mapped[str] = mapped_column(Text)
    input: Mapped[JsonObject] = mapped_column(JSONB, default=dict)
    report: Mapped[JsonObject | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[JsonObject | None] = mapped_column(JSONB, nullable=True)
    timeout_seconds: Mapped[int] = mapped_column(default=600)
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    colony: Mapped[ColonyModel] = relationship("ColonyModel", back_populates="workers")


__all__ = ["WorkerRunModel"]
