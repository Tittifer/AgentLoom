"""Tests for shared public API schemas."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from agentloom.api.schemas import ApiError, PaginatedResponse, TaskCreate, TaskRead


def test_task_create_uses_documented_defaults() -> None:
    task = TaskCreate(title="Research products", goal="Compare three products")

    assert task.context == {}
    assert task.max_parallel_nodes == 3
    assert task.max_retries == 2


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("title", "   "),
        ("goal", "   "),
        ("max_parallel_nodes", 0),
        ("max_parallel_nodes", 21),
        ("max_retries", -1),
    ],
)
def test_task_create_rejects_invalid_fields(field: str, value: object) -> None:
    payload: dict[str, object] = {
        "title": "Research products",
        "goal": "Compare three products",
        field: value,
    }

    with pytest.raises(ValidationError):
        TaskCreate.model_validate(payload)


def test_task_read_rejects_unknown_status() -> None:
    payload: dict[str, object] = {
        "id": uuid4(),
        "title": "Research products",
        "goal": "Compare three products",
        "status": "paused",
        "created_at": datetime.now(UTC),
    }

    with pytest.raises(ValidationError):
        TaskRead.model_validate(payload)


def test_task_create_rejects_non_json_context() -> None:
    payload: dict[str, object] = {
        "title": "Research products",
        "goal": "Compare three products",
        "context": {"unsupported": object()},
    }

    with pytest.raises(ValidationError):
        TaskCreate.model_validate(payload)


def test_task_read_rejects_naive_timestamp() -> None:
    payload: dict[str, object] = {
        "id": uuid4(),
        "title": "Research products",
        "goal": "Compare three products",
        "status": "draft",
        "created_at": datetime.now(),
    }

    with pytest.raises(ValidationError):
        TaskRead.model_validate(payload)


def test_api_error_matches_documented_shape() -> None:
    error = ApiError.model_validate(
        {
            "code": "WORKFLOW_INVALID",
            "message": "Workflow contains a cycle",
            "details": [{"path": "nodes.a", "reason": "cycle"}],
        }
    )

    assert error.model_dump() == {
        "code": "WORKFLOW_INVALID",
        "message": "Workflow contains a cycle",
        "details": [{"path": "nodes.a", "reason": "cycle"}],
    }


def test_paginated_response_validates_metadata() -> None:
    page = PaginatedResponse[TaskRead](items=[], page=1, page_size=20, total=0)

    assert page.model_dump() == {"items": [], "page": 1, "page_size": 20, "total": 0}

    with pytest.raises(ValidationError):
        PaginatedResponse[TaskRead](items=[], page=0, page_size=20, total=0)
