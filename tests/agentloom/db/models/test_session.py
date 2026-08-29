"""Metadata tests for agent sessions."""

from agentloom.db.models.session import AgentSessionModel


def test_session_references_colony_and_parent_session() -> None:
    foreign_keys = {key.target_fullname for key in AgentSessionModel.__table__.foreign_keys}
    assert foreign_keys == {"colonies.id", "agent_sessions.id"}
