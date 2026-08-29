"""Agent message persistence model."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from agentloom.db.base import Base, JsonObject, utc_now

if TYPE_CHECKING:
    from agentloom.db.models.run import NodeRunModel


def empty_tool_calls() -> list[JsonObject]:
    """Return an independent empty tool-call collection."""

    return []


class AgentMessageModel(Base):
    """A model-visible message recorded during one node attempt."""

    __tablename__ = "agent_messages"

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    node_run_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("node_runs.id", ondelete="CASCADE"),
    )
    role: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text)
    tool_calls: Mapped[list[JsonObject]] = mapped_column(JSONB, default=empty_tool_calls)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
    )

    node_run: Mapped[NodeRunModel] = relationship(
        "NodeRunModel",
        back_populates="messages",
    )
