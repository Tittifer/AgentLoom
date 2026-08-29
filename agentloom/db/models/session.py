"""Queen and worker agent-session persistence."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Literal
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from agentloom.db.base import Base, JsonObject, enum_values, utc_now
from agentloom.runtime.states import SessionStatus

if TYPE_CHECKING:
    from agentloom.db.models.colony import ColonyModel
    from agentloom.db.models.conversation import ConversationMessageModel

ActorType = Literal["queen", "worker"]


class AgentSessionModel(Base):
    """One durable execution loop and its checkpoint cursor."""

    __tablename__ = "agent_sessions"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    colony_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("colonies.id", ondelete="CASCADE"),
        index=True,
    )
    parent_session_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("agent_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    actor_type: Mapped[str] = mapped_column(String(20))
    status: Mapped[SessionStatus] = mapped_column(
        SqlEnum(
            SessionStatus,
            name="agent_session_status",
            values_callable=enum_values,
            validate_strings=True,
        ),
        default=SessionStatus.IDLE,
        index=True,
    )
    park_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    task: Mapped[JsonObject] = mapped_column(JSONB, default=dict)
    cursor: Mapped[JsonObject] = mapped_column(JSONB, default=dict)
    budget: Mapped[JsonObject] = mapped_column(JSONB, default=dict)
    usage: Mapped[JsonObject] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    colony: Mapped[ColonyModel] = relationship("ColonyModel", back_populates="sessions")
    messages: Mapped[list[ConversationMessageModel]] = relationship(
        "ConversationMessageModel",
        back_populates="session",
        passive_deletes=True,
        order_by="ConversationMessageModel.sequence",
    )


__all__ = ["ActorType", "AgentSessionModel"]
