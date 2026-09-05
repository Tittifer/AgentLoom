"""Tests for strict Colony DTO boundaries."""

import pytest
from pydantic import ValidationError

from agentloom.colony.schemas import (
    ColonyCreate,
    MessageCreate,
    QueenCreate,
    TrackerUpsert,
    WorkerTask,
)


def test_colony_create_applies_defaults() -> None:
    payload = ColonyCreate(name="研究空间", queen_id="queen_research")
    assert payload.queen_id == "queen_research"
    assert payload.settings == {}


def test_queen_requires_a_suffix_free_base_url() -> None:
    payload = QueenCreate(
        name="研究 Queen",
        model="gemini-2.5-pro",
        base_url="https://generativelanguage.googleapis.com/",
        api_key="test-key",
    )
    assert payload.base_url == "https://generativelanguage.googleapis.com"
    with pytest.raises(ValidationError):
        QueenCreate(
            name="错误 Queen",
            model="gpt-5",
            base_url="https://api.openai.com/v1",
            api_key="test-key",
        )


def test_colony_payloads_reject_empty_or_stale_values() -> None:
    with pytest.raises(ValidationError):
        MessageCreate(content=" ")
    with pytest.raises(ValidationError):
        WorkerTask(task="")
    with pytest.raises(ValidationError):
        TrackerUpsert(namespace="n", entry_key="k", expected_version=0)
