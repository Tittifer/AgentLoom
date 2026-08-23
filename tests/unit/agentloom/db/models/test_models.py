"""Metadata-level tests for SQLAlchemy persistence models."""

from collections.abc import Iterable
from datetime import UTC

from sqlalchemy import DateTime, Enum, ForeignKeyConstraint, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.dialects.postgresql import dialect as postgresql_dialect
from sqlalchemy.orm import configure_mappers
from sqlalchemy.schema import CreateTable
from sqlalchemy.sql.schema import Column, Table

from agentloom.db import Base
from agentloom.db.base import utc_now
from agentloom.runtime.states import NodeRunStatus, RunStatus, TaskStatus


def constraint_columns(constraint: UniqueConstraint) -> tuple[str, ...]:
    return tuple(column.name for column in constraint.columns)


def unique_constraints(table: Table) -> set[tuple[str, ...]]:
    return {
        constraint_columns(constraint)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }


def index_columns(indexes: Iterable[Index]) -> set[tuple[str, ...]]:
    return {tuple(column.name for column in index.columns) for index in indexes}


def assert_uuid_primary_key(table: Table) -> None:
    id_column = table.c.id
    assert id_column.primary_key
    assert isinstance(id_column.type, UUID)


def assert_timezone_aware(column: Column[object]) -> None:
    assert isinstance(column.type, DateTime)
    assert column.type.timezone is True


def test_all_models_are_registered_for_migrations() -> None:
    configure_mappers()

    assert set(Base.metadata.tables) == {
        "agent_messages",
        "node_runs",
        "run_events",
        "runs",
        "tasks",
        "workflow_edges",
        "workflow_nodes",
        "workflows",
    }


def test_all_tables_compile_for_postgresql() -> None:
    dialect = postgresql_dialect()

    for table in Base.metadata.sorted_tables:
        statement = str(CreateTable(table).compile(dialect=dialect))
        assert f"CREATE TABLE {table.name}" in statement


def test_all_models_use_uuid_primary_keys() -> None:
    for table in Base.metadata.sorted_tables:
        assert_uuid_primary_key(table)


def test_flexible_fields_use_postgresql_jsonb() -> None:
    jsonb_columns = {
        "tasks": {"context", "settings"},
        "workflow_nodes": {"tools", "output_schema"},
        "runs": {"input", "result", "error"},
        "node_runs": {"input", "output", "review", "usage", "error"},
        "agent_messages": {"tool_calls"},
        "run_events": {"payload"},
    }

    for table_name, column_names in jsonb_columns.items():
        table = Base.metadata.tables[table_name]
        for column_name in column_names:
            assert isinstance(table.c[column_name].type, JSONB)


def test_all_timestamp_columns_are_timezone_aware() -> None:
    timestamp_columns = {
        "tasks": {"created_at"},
        "workflows": {"created_at"},
        "runs": {"created_at", "started_at", "ended_at"},
        "node_runs": {"created_at", "started_at", "ended_at"},
        "agent_messages": {"created_at"},
        "run_events": {"created_at"},
    }

    for table_name, column_names in timestamp_columns.items():
        table = Base.metadata.tables[table_name]
        for column_name in column_names:
            assert_timezone_aware(table.c[column_name])


def test_utc_default_is_timezone_aware() -> None:
    timestamp = utc_now()

    assert timestamp.tzinfo is UTC


def test_status_columns_store_documented_enum_values() -> None:
    expected_values = {
        ("tasks", "status"): [status.value for status in TaskStatus],
        ("runs", "status"): [status.value for status in RunStatus],
        ("node_runs", "status"): [status.value for status in NodeRunStatus],
    }

    for (table_name, column_name), values in expected_values.items():
        enum_type = Base.metadata.tables[table_name].c[column_name].type
        assert isinstance(enum_type, Enum)
        assert enum_type.enums == values


def test_design_constraints_and_indexes_are_present() -> None:
    workflow_nodes = Base.metadata.tables["workflow_nodes"]
    node_runs = Base.metadata.tables["node_runs"]
    run_events = Base.metadata.tables["run_events"]
    runs = Base.metadata.tables["runs"]

    assert ("workflow_id", "node_key") in unique_constraints(workflow_nodes)
    assert ("run_id", "node_key", "attempt") in unique_constraints(node_runs)
    assert ("run_id", "sequence") in unique_constraints(run_events)
    assert ("status",) in index_columns(runs.indexes)
    assert ("run_id", "status") in index_columns(node_runs.indexes)


def test_workflow_edges_reference_nodes_in_the_same_workflow() -> None:
    workflow_edges = Base.metadata.tables["workflow_edges"]
    node_constraints = [
        constraint
        for constraint in workflow_edges.constraints
        if isinstance(constraint, ForeignKeyConstraint) and len(constraint.column_keys) == 2
    ]
    node_references = {
        tuple(element.target_fullname for element in constraint.elements)
        for constraint in node_constraints
    }

    assert len(node_constraints) == 2
    assert node_references == {("workflow_nodes.workflow_id", "workflow_nodes.node_key")}
