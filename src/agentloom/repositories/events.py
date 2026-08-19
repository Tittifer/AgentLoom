"""Ordered run-event persistence operations."""

from collections.abc import Mapping
from uuid import UUID

from pydantic import JsonValue, TypeAdapter
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agentloom.db.models.event import RunEventModel
from agentloom.db.models.run import RunModel
from agentloom.runtime.run import RunEventRead, RunEventType

JSON_OBJECT_ADAPTER = TypeAdapter(dict[str, JsonValue])
RUN_EVENT_TYPE_ADAPTER: TypeAdapter[RunEventType] = TypeAdapter(RunEventType)


class RunEventRepository:
    """Persist and replay events ordered within a single run."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def lock_run(self, run_id: UUID) -> bool:
        """Serialize event sequence allocation by locking the owning run."""

        locked_run_id = await self._session.scalar(
            select(RunModel.id).where(RunModel.id == run_id).with_for_update()
        )
        return locked_run_id is not None

    async def next_sequence(self, run_id: UUID) -> int:
        """Return the next sequence after the caller has locked the run."""

        sequence = await self._session.scalar(
            select(func.coalesce(func.max(RunEventModel.sequence), 0) + 1).where(
                RunEventModel.run_id == run_id
            )
        )
        if sequence is None:
            raise RuntimeError(f"Could not allocate an event sequence for run {run_id}")
        return sequence

    async def create(
        self,
        run_id: UUID,
        sequence: int,
        event_type: RunEventType,
        node_key: str | None,
        payload: Mapping[str, object],
    ) -> RunEventRead:
        """Flush one event into the caller's transaction."""

        event = RunEventModel(
            run_id=run_id,
            sequence=sequence,
            type=event_type,
            node_key=node_key,
            payload=dict(payload),
        )
        self._session.add(event)
        await self._session.flush()
        return self._to_event_read(event)

    async def list_after(self, run_id: UUID, sequence: int) -> list[RunEventRead]:
        """Return all events newer than a client cursor."""

        statement = (
            select(RunEventModel)
            .where(
                RunEventModel.run_id == run_id,
                RunEventModel.sequence > sequence,
            )
            .order_by(RunEventModel.sequence)
        )
        events = (await self._session.scalars(statement)).all()
        return [self._to_event_read(event) for event in events]

    async def run_exists(self, run_id: UUID) -> bool:
        """Return whether an event stream target exists."""

        return (
            await self._session.scalar(select(RunModel.id).where(RunModel.id == run_id)) is not None
        )

    @staticmethod
    def _to_event_read(event: RunEventModel) -> RunEventRead:
        return RunEventRead(
            id=event.id,
            run_id=event.run_id,
            sequence=event.sequence,
            type=RUN_EVENT_TYPE_ADAPTER.validate_python(event.type),
            node_key=event.node_key,
            payload=JSON_OBJECT_ADAPTER.validate_python(event.payload),
            created_at=event.created_at,
        )


__all__ = ["RunEventRepository"]
