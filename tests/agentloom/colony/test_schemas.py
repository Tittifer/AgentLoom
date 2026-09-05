"""Tests for strict Colony DTO boundaries."""

import pytest
from pydantic import ValidationError

from agentloom.colony.schemas import ColonyCreate, MessageCreate, TrackerUpsert, WorkerTask


def test_colony_create_applies_defaults() -> None:
    payload = ColonyCreate(name="研究空间")
    assert payload.queen_id == "general"
    assert payload.settings == {}


def test_colony_payloads_reject_empty_or_stale_values() -> None:
    with pytest.raises(ValidationError):
        MessageCreate(content=" ")
    with pytest.raises(ValidationError):
        WorkerTask(task="")
    with pytest.raises(ValidationError):
        TrackerUpsert(namespace="n", entry_key="k", expected_version=0)
