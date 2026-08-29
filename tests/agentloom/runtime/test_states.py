"""Tests for canonical lifecycle states."""

from agentloom.runtime.states import NodeRunStatus, RunStatus, TaskStatus


def test_task_status_values_match_design() -> None:
    assert [status.value for status in TaskStatus] == [
        "draft",
        "planning",
        "ready",
        "running",
        "completed",
        "failed",
        "cancelled",
    ]


def test_run_status_values_match_design() -> None:
    assert [status.value for status in RunStatus] == [
        "queued",
        "running",
        "completed",
        "failed",
        "cancelled",
    ]


def test_node_run_status_values_match_design() -> None:
    assert [status.value for status in NodeRunStatus] == [
        "pending",
        "running",
        "reviewing",
        "retrying",
        "completed",
        "failed",
        "skipped",
        "cancelled",
    ]
