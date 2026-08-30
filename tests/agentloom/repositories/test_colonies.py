"""Tests for Colony repository domain errors."""

from uuid import UUID

from agentloom.repositories.colonies import TrackerVersionConflictError, colony_lock_key


def test_tracker_version_conflict_is_a_domain_value_error() -> None:
    assert issubclass(TrackerVersionConflictError, ValueError)


def test_colony_lock_key_is_deterministic_signed_bigint() -> None:
    colony_id = UUID("9c1c4357-8e09-42c0-b39f-aee8d00b0e56")

    key = colony_lock_key(colony_id)

    assert key == colony_lock_key(colony_id)
    assert -(1 << 63) <= key < 1 << 63
    assert colony_lock_key(UUID(int=0)) != colony_lock_key(UUID(int=1))
