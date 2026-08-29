"""Unit tests for Colony API wire helpers."""

from datetime import UTC, datetime
from uuid import uuid4

from agentloom.api.routes.colonies import error_response, format_sse_event
from agentloom.colony.schemas import ColonyEventRead


def test_colony_route_formats_errors_and_replayable_sse() -> None:
    response = error_response(404, "COLONY_NOT_FOUND", "不存在")
    assert response.status_code == 404
    event = ColonyEventRead(
        id=uuid4(),
        colony_id=uuid4(),
        session_id=None,
        worker_run_id=None,
        sequence=3,
        type="colony.created",
        payload={"name": "研究"},
        created_at=datetime.now(UTC),
    )
    encoded = format_sse_event(event)
    assert "id: 3\n" in encoded
    assert "event: colony.created\n" in encoded
    assert '"name":"研究"' in encoded
