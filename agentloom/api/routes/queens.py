"""Queen identity and owned-session endpoints."""

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from agentloom.api.routes.colonies import RuntimeDependency, error_response
from agentloom.api.schemas import ApiError
from agentloom.colony.runtime import QueenNotFoundError
from agentloom.colony.schemas import QueenCreate, QueenRead, SessionRead

router = APIRouter(prefix="/queens", tags=["queens"])


@router.post(
    "",
    response_model=QueenRead,
    status_code=status.HTTP_201_CREATED,
    responses={status.HTTP_409_CONFLICT: {"model": ApiError}},
)
async def create_queen(
    payload: QueenCreate,
    runtime: RuntimeDependency,
) -> QueenRead | JSONResponse:
    try:
        return await runtime.create_queen(payload)
    except FileExistsError:
        return error_response(409, "QUEEN_EXISTS", "Queen 标识已存在")


@router.get("", response_model=list[QueenRead])
async def list_queens(runtime: RuntimeDependency) -> list[QueenRead]:
    return await runtime.list_queens()


@router.get(
    "/{queen_id}",
    response_model=QueenRead,
    responses={status.HTTP_404_NOT_FOUND: {"model": ApiError}},
)
async def get_queen(
    queen_id: str,
    runtime: RuntimeDependency,
) -> QueenRead | JSONResponse:
    try:
        return await runtime.get_queen(queen_id)
    except QueenNotFoundError:
        return error_response(404, "QUEEN_NOT_FOUND", "Queen 不存在")


@router.get(
    "/{queen_id}/sessions",
    response_model=list[SessionRead],
    responses={status.HTTP_404_NOT_FOUND: {"model": ApiError}},
)
async def list_queen_sessions(
    queen_id: str,
    runtime: RuntimeDependency,
) -> list[SessionRead] | JSONResponse:
    try:
        return await runtime.list_queen_sessions(queen_id)
    except QueenNotFoundError:
        return error_response(404, "QUEEN_NOT_FOUND", "Queen 不存在")


__all__ = ["router"]
