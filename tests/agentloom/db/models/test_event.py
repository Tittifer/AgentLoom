"""Metadata-level tests for the RunEvent persistence model."""

from sqlalchemy import DateTime, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.dialects.postgresql import dialect as postgresql_dialect
from sqlalchemy.schema import CreateTable

from agentloom.db import Base
from agentloom.db.models.event import RunEventModel


def test_run_event_table_matches_the_persisted_event_contract() -> None:
    table = Base.metadata.tables[RunEventModel.__tablename__]
    statement = str(CreateTable(table).compile(dialect=postgresql_dialect()))
    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert "CREATE TABLE run_events" in statement
    assert table.c.id.primary_key
    assert isinstance(table.c.id.type, UUID)
    assert isinstance(table.c.payload.type, JSONB)
    assert isinstance(table.c.created_at.type, DateTime)
    assert table.c.created_at.type.timezone is True
    assert ("run_id", "sequence") in unique_columns
