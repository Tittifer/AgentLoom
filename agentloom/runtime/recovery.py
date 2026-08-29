"""Database-backed recovery for runs interrupted by a backend restart."""

from collections import Counter
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentloom.db.models.run import NodeRunModel, RunModel
from agentloom.repositories.events import RunEventRepository
from agentloom.runtime.states import NodeRunStatus, RunStatus
from agentloom.services.event_service import EventService, RunEventNotifier


async def recover_active_runs(
    session_factory: async_sessionmaker[AsyncSession],
    notifier: RunEventNotifier,
) -> list[UUID]:
    """Reset interrupted attempts and record recovery before scheduling resumes."""

    recovered_run_ids: list[UUID] = []
    reset_counts: Counter[UUID] = Counter()
    async with session_factory.begin() as session:
        recovered_run_ids = list(
            (
                await session.scalars(
                    select(RunModel.id)
                    .where(RunModel.status.in_([RunStatus.QUEUED, RunStatus.RUNNING]))
                    .order_by(RunModel.created_at, RunModel.id)
                    .with_for_update()
                )
            ).all()
        )
        if not recovered_run_ids:
            return []

        reset_run_ids = (
            await session.scalars(
                update(NodeRunModel)
                .where(
                    NodeRunModel.run_id.in_(recovered_run_ids),
                    NodeRunModel.status.in_([NodeRunStatus.RUNNING, NodeRunStatus.REVIEWING]),
                )
                .values(
                    status=NodeRunStatus.PENDING,
                    output=None,
                    review=None,
                    usage=None,
                    error=None,
                    started_at=None,
                    ended_at=None,
                )
                .returning(NodeRunModel.run_id)
            )
        ).all()
        reset_counts.update(reset_run_ids)

        events = EventService(RunEventRepository(session))
        for run_id in recovered_run_ids:
            await events.append(
                run_id,
                "run.recovered",
                payload={
                    "status": "running",
                    "reset_nodes": reset_counts[run_id],
                },
            )

    for run_id in recovered_run_ids:
        await notifier.notify(run_id)
    return recovered_run_ids


__all__ = ["recover_active_runs"]
