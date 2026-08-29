"""Tests for Colony repository domain errors."""

from agentloom.repositories.colonies import TrackerVersionConflictError


def test_tracker_version_conflict_is_a_domain_value_error() -> None:
    assert issubclass(TrackerVersionConflictError, ValueError)
