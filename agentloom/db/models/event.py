"""Run event persistence model."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from agentloom.db.base import Base, JsonObject, utc_now

if TYPE_CHECKING:
    from agentloom.db.models.run import RunModel


class RunEventModel(Base):
    """An ordered event used for run history and SSE replay."""

    __tablename__ = "run_events"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "sequence",
            name="uq_run_events_run_id_sequence",
        ),
        CheckConstraint("sequence > 0", name="sequence_positive"),
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
    sequence: Mapped[int] = mapped_column(BigInteger)
    type: Mapped[str] = mapped_column(String(100))
    node_key: Mapped[str | None] = mapped_column(String(100))
    payload: Mapped[JsonObject] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
    )

    run: Mapped[RunModel] = relationship("RunModel", back_populates="events")
