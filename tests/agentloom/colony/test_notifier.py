"""Tests for local Colony SSE wake-up coordination."""

from uuid import uuid4

from agentloom.colony.notifier import ColonyEventNotifier


async def test_notifier_reports_change_and_timeout() -> None:
    notifier = ColonyEventNotifier()
    colony_id = uuid4()
    observed = notifier.version(colony_id)
    await notifier.notify(colony_id)
    assert await notifier.wait_for_change(colony_id, observed, timeout=0.01)
    assert not await notifier.wait_for_change(
        colony_id,
        notifier.version(colony_id),
        timeout=0.001,
    )
