"""Metadata-level tests for Run and NodeRun persistence models."""

from sqlalchemy import DateTime, Enum, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.dialects.postgresql import dialect as postgresql_dialect
from sqlalchemy.schema import CreateTable
from sqlalchemy.sql.schema import Table

from agentloom.db import Base
from agentloom.db.models.run import NodeRunModel, RunModel
from agentloom.runtime.states import NodeRunStatus, RunStatus


def unique_constraints(table: Table) -> set[tuple[str, ...]]:
    return {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }


def test_run_tables_compile_and_use_uuid_primary_keys() -> None:
    for table_name in (RunModel.__tablename__, NodeRunModel.__tablename__):
        table = Base.metadata.tables[table_name]
        statement = str(CreateTable(table).compile(dialect=postgresql_dialect()))
        assert f"CREATE TABLE {table.name}" in statement
        assert table.c.id.primary_key
        assert isinstance(table.c.id.type, UUID)


def test_run_fields_use_jsonb_and_timezone_aware_timestamps() -> None:
    expected_jsonb = {
        RunModel.__tablename__: {"input", "result", "error"},
        NodeRunModel.__tablename__: {"input", "output", "review", "usage", "error"},
    }
    for table_name, column_names in expected_jsonb.items():
        table = Base.metadata.tables[table_name]
        for column_name in column_names:
            assert isinstance(table.c[column_name].type, JSONB)
        for column_name in ("created_at", "started_at", "ended_at"):
            column_type = table.c[column_name].type
            assert isinstance(column_type, DateTime)
            assert column_type.timezone is True


def test_run_statuses_constraints_and_indexes_match_runtime_contracts() -> None:
    runs = Base.metadata.tables[RunModel.__tablename__]
    node_runs = Base.metadata.tables[NodeRunModel.__tablename__]
    run_status = runs.c.status.type
    node_status = node_runs.c.status.type

    assert isinstance(run_status, Enum)
    assert run_status.enums == [status.value for status in RunStatus]
    assert isinstance(node_status, Enum)
    assert node_status.enums == [status.value for status in NodeRunStatus]
    assert ("run_id", "node_key", "attempt") in unique_constraints(node_runs)
    assert {tuple(column.name for column in index.columns) for index in runs.indexes} == {
        ("status",)
    }
    assert {tuple(column.name for column in index.columns) for index in node_runs.indexes} == {
        ("run_id", "status")
    }
