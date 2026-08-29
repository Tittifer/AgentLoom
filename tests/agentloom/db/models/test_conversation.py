"""Metadata tests for conversation messages."""

from agentloom.db import Base
from agentloom.db.models.conversation import ConversationMessageModel


def test_conversation_sequence_is_unique_per_session() -> None:
    table = Base.metadata.tables[ConversationMessageModel.__tablename__]
    constraints = {constraint.name for constraint in table.constraints}
    assert "uq_conversation_session_sequence" in constraints
