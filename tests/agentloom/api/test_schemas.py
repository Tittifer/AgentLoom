"""Tests for shared API error contracts."""

import pytest
from pydantic import ValidationError

from agentloom.api.schemas import ApiError, HealthResponse


def test_api_error_and_health_shapes_are_strict() -> None:
    assert HealthResponse(status="ok").model_dump() == {"status": "ok"}
    error = ApiError(code="COLONY_NOT_FOUND", message="不存在")
    assert error.model_dump() == {
        "code": "COLONY_NOT_FOUND",
        "message": "不存在",
        "details": [],
    }
    with pytest.raises(ValidationError):
        HealthResponse.model_validate({"status": "ok", "extra": True})
