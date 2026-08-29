"""Metadata tests for the shared Tracker."""

from agentloom.db import Base
from agentloom.db.models.tracker import TrackerEntryModel


def test_tracker_key_is_unique_inside_namespace() -> None:
    table = Base.metadata.tables[TrackerEntryModel.__tablename__]
    constraints = {constraint.name for constraint in table.constraints}
    assert "uq_tracker_colony_namespace_key" in constraints
