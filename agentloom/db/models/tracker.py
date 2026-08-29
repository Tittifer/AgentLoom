"""Shared colony tracker ledger persistence."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from agentloom.db.base import Base, JsonObject, utc_now

if TYPE_CHECKING:
    from agentloom.db.models.colony import ColonyModel


class TrackerEntryModel(Base):
    """One versioned structured fact shared by a colony."""

    __tablename__ = "tracker_entries"
    __table_args__ = (
        UniqueConstraint(
            "colony_id", "namespace", "entry_key", name="uq_tracker_colony_namespace_key"
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    colony_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("colonies.id", ondelete="CASCADE"),
        index=True,
    )
    namespace: Mapped[str] = mapped_column(String(100))
    entry_key: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(50), default="pending")
    data: Mapped[JsonObject] = mapped_column(JSONB, default=dict)
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_by_session_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("agent_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    colony: Mapped[ColonyModel] = relationship("ColonyModel", back_populates="tracker_entries")


__all__ = ["TrackerEntryModel"]
