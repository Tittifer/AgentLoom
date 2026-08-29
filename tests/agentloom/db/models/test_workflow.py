"""Metadata-level tests for Workflow persistence models."""

from sqlalchemy import DateTime, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.dialects.postgresql import dialect as postgresql_dialect
from sqlalchemy.schema import CreateTable
from sqlalchemy.sql.schema import Table

from agentloom.db import Base
from agentloom.db.models.workflow import (
    WorkflowEdgeModel,
    WorkflowModel,
    WorkflowNodeModel,
)


def unique_constraints(table: Table) -> set[tuple[str, ...]]:
    return {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }


def test_workflow_tables_compile_and_use_uuid_primary_keys() -> None:
    for table_name in (
        WorkflowModel.__tablename__,
        WorkflowNodeModel.__tablename__,
        WorkflowEdgeModel.__tablename__,
    ):
        table = Base.metadata.tables[table_name]
        statement = str(CreateTable(table).compile(dialect=postgresql_dialect()))
        assert f"CREATE TABLE {table.name}" in statement
        assert table.c.id.primary_key
        assert isinstance(table.c.id.type, UUID)


def test_workflow_fields_use_expected_postgresql_types() -> None:
    workflow = Base.metadata.tables[WorkflowModel.__tablename__]
    node = Base.metadata.tables[WorkflowNodeModel.__tablename__]

    assert isinstance(workflow.c.created_at.type, DateTime)
    assert workflow.c.created_at.type.timezone is True
    assert isinstance(node.c.tools.type, JSONB)
    assert isinstance(node.c.output_schema.type, JSONB)


def test_workflow_constraints_keep_edges_inside_the_same_workflow() -> None:
    nodes = Base.metadata.tables[WorkflowNodeModel.__tablename__]
    edges = Base.metadata.tables[WorkflowEdgeModel.__tablename__]
    node_constraints = [
        constraint
        for constraint in edges.constraints
        if isinstance(constraint, ForeignKeyConstraint) and len(constraint.column_keys) == 2
    ]
    node_references = {
        tuple(element.target_fullname for element in constraint.elements)
        for constraint in node_constraints
    }

    assert ("workflow_id", "node_key") in unique_constraints(nodes)
    assert len(node_constraints) == 2
    assert node_references == {("workflow_nodes.workflow_id", "workflow_nodes.node_key")}
    assert nodes.name == "workflow_nodes"
