"""Metadata-level tests for the AgentMessage persistence model."""

from sqlalchemy import DateTime
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.dialects.postgresql import dialect as postgresql_dialect
from sqlalchemy.schema import CreateTable

from agentloom.db import Base
from agentloom.db.models.message import AgentMessageModel, empty_tool_calls


def test_agent_message_table_matches_the_visible_message_contract() -> None:
    table = Base.metadata.tables[AgentMessageModel.__tablename__]
    statement = str(CreateTable(table).compile(dialect=postgresql_dialect()))

    assert "CREATE TABLE agent_messages" in statement
    assert table.c.id.primary_key
    assert isinstance(table.c.id.type, UUID)
    assert isinstance(table.c.tool_calls.type, JSONB)
    assert isinstance(table.c.created_at.type, DateTime)
    assert table.c.created_at.type.timezone is True


def test_empty_tool_calls_returns_an_independent_list() -> None:
    first = empty_tool_calls()
    second = empty_tool_calls()

    assert first == []
    assert second == []
    assert second is not first
