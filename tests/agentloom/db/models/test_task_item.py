"""Metadata tests for Queen task-plan items."""

from agentloom.db.models.task_item import TaskItemModel


def test_task_item_supports_parent_and_worker_links() -> None:
    foreign_keys = {key.target_fullname for key in TaskItemModel.__table__.foreign_keys}
    assert "task_items.id" in foreign_keys
    assert "worker_runs.id" in foreign_keys
