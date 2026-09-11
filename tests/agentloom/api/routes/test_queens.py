"""Unit tests for Queen identity and session route delegation."""

import json
from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

from fastapi.responses import JSONResponse

from agentloom.api.routes.queens import (
    create_queen,
    create_queen_session,
    get_queen,
    list_queen_sessions,
    list_queens,
)
from agentloom.colony.runtime import ColonyRuntime, QueenNotFoundError
from agentloom.colony.schemas import QueenCreate, QueenRead, SessionRead
from agentloom.runtime.states import SessionStatus


class FakeRuntime:
    def __init__(self, queen: QueenRead, session: SessionRead) -> None:
        self.queen = queen
        self.session = session
        self.fail_create = False
        self.missing = False

    async def create_queen(self, payload: QueenCreate) -> QueenRead:
        if self.fail_create:
            raise FileExistsError(payload.name)
        return self.queen

    async def list_queens(self) -> list[QueenRead]:
        return [self.queen]

    async def get_queen(self, queen_id: str) -> QueenRead:
        if self.missing:
            raise QueenNotFoundError(queen_id)
        return self.queen

    async def list_queen_sessions(self, queen_id: str) -> list[SessionRead]:
        if self.missing:
            raise QueenNotFoundError(queen_id)
        return []

    async def create_queen_session(self, queen_id: str) -> SessionRead:
        if self.missing:
            raise QueenNotFoundError(queen_id)
        return self.session


def error_code(response: JSONResponse) -> str:
    payload = json.loads(bytes(response.body))
    return str(payload["code"])


def make_session(now: datetime) -> SessionRead:
    return SessionRead(
        id=uuid4(),
        queen_id="general",
        parent_session_id=None,
        actor_type="queen",
        status=SessionStatus.IDLE,
        park_reason=None,
        task={},
        cursor={},
        budget={},
        usage={},
        created_at=now,
        updated_at=now,
        ended_at=None,
    )


async def test_queen_routes_delegate_successfully() -> None:
    now = datetime.now(UTC)
    queen = QueenRead(id="general", name="General", created_at=now, updated_at=now)
    session = make_session(now)
    fake = FakeRuntime(queen, session)
    runtime = cast(ColonyRuntime, fake)

    assert await create_queen(QueenCreate(name="General"), runtime) == queen
    assert await list_queens(runtime) == [queen]
    assert await get_queen("general", runtime) == queen
    assert await list_queen_sessions("general", runtime) == []
    assert await create_queen_session("general", runtime) == session


async def test_queen_routes_return_stable_domain_errors() -> None:
    now = datetime.now(UTC)
    queen = QueenRead(id="general", name="General", created_at=now, updated_at=now)
    fake = FakeRuntime(queen, make_session(now))
    runtime = cast(ColonyRuntime, fake)

    fake.fail_create = True
    duplicate = await create_queen(QueenCreate(name="General"), runtime)
    assert isinstance(duplicate, JSONResponse)
    assert duplicate.status_code == 409
    assert error_code(duplicate) == "QUEEN_EXISTS"

    fake.missing = True
    missing_queen = await get_queen("missing", runtime)
    missing_sessions = await list_queen_sessions("missing", runtime)
    missing_created = await create_queen_session("missing", runtime)
    for response in (missing_queen, missing_sessions, missing_created):
        assert isinstance(response, JSONResponse)
        assert response.status_code == 404
        assert error_code(response) == "QUEEN_NOT_FOUND"
