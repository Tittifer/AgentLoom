"""Canonical Colony lifecycle states."""

from enum import StrEnum


class ColonyStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    ARCHIVED = "archived"


class SessionStatus(StrEnum):
    IDLE = "idle"
    QUEUED = "queued"
    RUNNING = "running"
    PARKED = "parked"
    FORKED = "forked"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkerStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    REPORTING = "reporting"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


ACTIVE_WORKER_STATUSES = frozenset(
    {
        WorkerStatus.QUEUED,
        WorkerStatus.RUNNING,
        WorkerStatus.REPORTING,
    }
)
TERMINAL_WORKER_STATUSES = frozenset(
    {
        WorkerStatus.COMPLETED,
        WorkerStatus.PARTIAL,
        WorkerStatus.FAILED,
        WorkerStatus.TIMED_OUT,
        WorkerStatus.CANCELLED,
    }
)


class TaskItemStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


__all__ = [
    "ACTIVE_WORKER_STATUSES",
    "ColonyStatus",
    "SessionStatus",
    "TERMINAL_WORKER_STATUSES",
    "TaskItemStatus",
    "WorkerStatus",
]
