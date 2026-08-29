"""Metadata tests for replayable Colony events."""

from agentloom.db import Base
from agentloom.db.models.colony_event import ColonyEventModel


def test_colony_event_sequence_is_unique() -> None:
    table = Base.metadata.tables[ColonyEventModel.__tablename__]
    constraints = {constraint.name for constraint in table.constraints}
    assert "uq_colony_events_colony_sequence" in constraints
