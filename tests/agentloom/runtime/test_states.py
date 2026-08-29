"""Tests for canonical Colony lifecycle states."""

from agentloom.runtime.states import ColonyStatus, SessionStatus, TaskItemStatus, WorkerStatus


def test_colony_runtime_states_match_public_contracts() -> None:
    assert ColonyStatus.ACTIVE == "active"
    assert SessionStatus.IDLE == "idle"
    assert WorkerStatus.TIMED_OUT == "timed_out"
    assert TaskItemStatus.IN_PROGRESS == "in_progress"
