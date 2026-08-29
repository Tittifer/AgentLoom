"""Metadata tests for dynamic Worker runs."""

from agentloom.db.models.worker import WorkerRunModel


def test_worker_run_owns_a_unique_worker_session() -> None:
    assert WorkerRunModel.__table__.c.worker_session_id.unique
    assert WorkerRunModel.__table__.c.timeout_seconds.nullable is False
