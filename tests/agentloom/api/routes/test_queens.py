"""Unit tests for Queen identity route delegation."""

import json
from datetime import UTC, datetime
from typing import cast

from fastapi.responses import JSONResponse

from agentloom.api.routes.queens import create_queen, get_queen, list_queens
from agentloom.colony.runtime import ColonyRuntime, QueenNotFoundError
from agentloom.colony.schemas import QueenCreate, QueenRead


class FakeRuntime:
    def __init__(self, queen: QueenRead) -> None:
        self.queen = queen
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


def error_code(response: JSONResponse) -> str:
    payload = json.loads(bytes(response.body))
    return str(payload["code"])


async def test_queen_routes_delegate_identity_operations() -> None:
    now = datetime.now(UTC)
    queen = QueenRead(id="general", name="General", created_at=now, updated_at=now)
    fake = FakeRuntime(queen)
    runtime = cast(ColonyRuntime, fake)

    assert await create_queen(QueenCreate(name="General"), runtime) == queen
    assert await list_queens(runtime) == [queen]
    assert await get_queen("general", runtime) == queen


async def test_queen_routes_return_stable_domain_errors() -> None:
    now = datetime.now(UTC)
    queen = QueenRead(id="general", name="General", created_at=now, updated_at=now)
    fake = FakeRuntime(queen)
    runtime = cast(ColonyRuntime, fake)

    fake.fail_create = True
    duplicate = await create_queen(QueenCreate(name="General"), runtime)
    assert isinstance(duplicate, JSONResponse)
    assert duplicate.status_code == 409
    assert error_code(duplicate) == "QUEEN_EXISTS"

    fake.missing = True
    missing_queen = await get_queen("missing", runtime)
    assert isinstance(missing_queen, JSONResponse)
    assert missing_queen.status_code == 404
    assert error_code(missing_queen) == "QUEEN_NOT_FOUND"
