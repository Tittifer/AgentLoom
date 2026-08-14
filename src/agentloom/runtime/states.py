"""Canonical lifecycle states shared by persistence and runtime code."""

from enum import StrEnum


class TaskStatus(StrEnum):
    """Lifecycle state of a user task."""

    DRAFT = "draft"
    PLANNING = "planning"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RunStatus(StrEnum):
    """Lifecycle state of one task execution."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class NodeRunStatus(StrEnum):
    """Lifecycle state of one workflow node execution."""

    PENDING = "pending"
    RUNNING = "running"
    REVIEWING = "reviewing"
    RETRYING = "retrying"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


__all__ = ["NodeRunStatus", "RunStatus", "TaskStatus"]
