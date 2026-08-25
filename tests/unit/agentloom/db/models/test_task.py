"""Metadata-level tests for the Task persistence model."""

from sqlalchemy import DateTime, Enum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.dialects.postgresql import dialect as postgresql_dialect
from sqlalchemy.schema import CreateTable

from agentloom.db import Base
from agentloom.db.models.task import TaskModel, default_task_settings
from agentloom.runtime.states import TaskStatus


def test_task_table_compiles_with_expected_postgresql_types() -> None:
    table = Base.metadata.tables[TaskModel.__tablename__]
    statement = str(CreateTable(table).compile(dialect=postgresql_dialect()))

    assert "CREATE TABLE tasks" in statement
    assert table.c.id.primary_key
    assert isinstance(table.c.id.type, UUID)
    assert isinstance(table.c.context.type, JSONB)
    assert isinstance(table.c.settings.type, JSONB)
    assert isinstance(table.c.created_at.type, DateTime)
    assert table.c.created_at.type.timezone is True


def test_task_status_uses_documented_enum_values() -> None:
    status_type = Base.metadata.tables[TaskModel.__tablename__].c.status.type

    assert isinstance(status_type, Enum)
    assert status_type.enums == [status.value for status in TaskStatus]


def test_default_task_settings_returns_independent_values() -> None:
    first = default_task_settings()
    second = default_task_settings()

    assert first == {"max_parallel_nodes": 3, "max_retries": 2}
    assert second == first
    assert second is not first
