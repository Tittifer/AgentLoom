"""Metadata tests for Colony persistence."""

from sqlalchemy.dialects.postgresql import JSONB

from agentloom.db.models.colony import ColonyModel, default_colony_settings


def test_colony_table_uses_json_settings_and_independent_defaults() -> None:
    assert isinstance(ColonyModel.__table__.c.settings.type, JSONB)
    first = default_colony_settings()
    second = default_colony_settings()
    assert first["max_concurrent_workers"] == 4
    assert first["worker_max_turns"] == 8
    assert first == second and first is not second
