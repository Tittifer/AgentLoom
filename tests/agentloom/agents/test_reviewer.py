"""Tests for deterministic structured-output review."""

from pydantic import JsonValue

from agentloom.agents.reviewer import DeterministicReviewer


def schema() -> dict[str, JsonValue]:
    return {
        "type": "object",
        "required": ["summary", "sources"],
        "properties": {
            "summary": {"type": "string"},
            "sources": {
                "type": "array",
                "minItems": 1,
                "items": {"type": "string"},
            },
        },
        "additionalProperties": False,
    }


def test_reviewer_requires_structured_output() -> None:
    review = DeterministicReviewer().review(None, schema())

    assert review.decision == "retry"
    assert "structured" in review.feedback


def test_reviewer_reports_schema_path_and_array_length() -> None:
    review = DeterministicReviewer().review({"summary": "ok", "sources": []}, schema())

    assert review.decision == "retry"
    assert "sources" in review.feedback


def test_reviewer_rejects_an_invalid_configured_schema() -> None:
    review = DeterministicReviewer().review(
        {"summary": "ok"},
        {"type": "not-a-json-schema-type"},
    )

    assert review.decision == "reject"
    assert "configured output schema" in review.feedback


def test_reviewer_retries_an_empty_required_string() -> None:
    review = DeterministicReviewer().review(
        {"summary": "  ", "sources": ["source"]},
        schema(),
    )

    assert review.decision == "retry"
    assert "$.summary" in review.feedback


def test_reviewer_accepts_valid_output() -> None:
    review = DeterministicReviewer().review(
        {"summary": "valid", "sources": ["source"]},
        schema(),
    )

    assert review.decision == "accept"
    assert review.score == 1
