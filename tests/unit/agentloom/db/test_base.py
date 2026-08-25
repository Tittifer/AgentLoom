"""Tests for shared SQLAlchemy base helpers."""

from datetime import UTC

from agentloom.db.base import utc_now


def test_utc_default_is_timezone_aware() -> None:
    timestamp = utc_now()

    assert timestamp.tzinfo is UTC
