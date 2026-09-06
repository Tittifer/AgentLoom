"""Safe CRUD endpoints for Markdown long-term memories."""

from fastapi import APIRouter, Query, status
from fastapi.responses import JSONResponse

from agentloom.api.routes.colonies import RuntimeDependency, error_response
from agentloom.api.schemas import ApiError
from agentloom.memory.schemas import MemoryRead, MemoryScope, MemoryWrite

router = APIRouter(prefix="/memories", tags=["memories"])


def _parse_path(path: str) -> tuple[MemoryScope, str | None, str]:
    parts = path.replace("\\", "/").split("/")
    if len(parts) == 2 and parts[0] == "global":
        return "global", None, parts[1]
    if len(parts) == 4 and parts[:2] == ["agents", "queens"]:
        return "queen", parts[2], parts[3]
    raise ValueError("记忆路径必须位于 global/ 或 agents/queens/<queen_id>/")


@router.get("", response_model=list[MemoryRead])
async def list_memories(runtime: RuntimeDependency) -> list[MemoryRead]:
    return await runtime.memory_store.list_all()


@router.get(
    "/file",
    response_model=MemoryRead,
    responses={400: {"model": ApiError}, 404: {"model": ApiError}},
)
async def get_memory(
    runtime: RuntimeDependency,
    path: str = Query(min_length=1),
) -> MemoryRead | JSONResponse:
    try:
        scope, queen_id, filename = _parse_path(path)
        item = await runtime.memory_store.read(scope, filename, queen_id)
    except ValueError as error:
        return error_response(400, "INVALID_MEMORY_PATH", str(error))
    if item is None:
        return error_response(404, "MEMORY_NOT_FOUND", "记忆不存在")
    return item


@router.post(
    "/file",
    response_model=MemoryRead,
    status_code=status.HTTP_201_CREATED,
    responses={400: {"model": ApiError}, 409: {"model": ApiError}},
)
async def create_memory(
    payload: MemoryWrite,
    runtime: RuntimeDependency,
    path: str = Query(min_length=1),
) -> MemoryRead | JSONResponse:
    try:
        scope, queen_id, filename = _parse_path(path)
        return await runtime.memory_store.write(
            scope,
            filename,
            payload.content,
            queen_id,
            overwrite=False,
        )
    except FileExistsError:
        return error_response(409, "MEMORY_EXISTS", "记忆已经存在")
    except ValueError as error:
        return error_response(400, "INVALID_MEMORY", str(error))


@router.put(
    "/file",
    response_model=MemoryRead,
    responses={400: {"model": ApiError}, 404: {"model": ApiError}},
)
async def update_memory(
    payload: MemoryWrite,
    runtime: RuntimeDependency,
    path: str = Query(min_length=1),
) -> MemoryRead | JSONResponse:
    try:
        scope, queen_id, filename = _parse_path(path)
        if await runtime.memory_store.read(scope, filename, queen_id) is None:
            return error_response(404, "MEMORY_NOT_FOUND", "记忆不存在")
        return await runtime.memory_store.write(scope, filename, payload.content, queen_id)
    except ValueError as error:
        return error_response(400, "INVALID_MEMORY", str(error))


@router.delete(
    "/file",
    response_model=dict[str, str],
    responses={400: {"model": ApiError}, 404: {"model": ApiError}},
)
async def delete_memory(
    runtime: RuntimeDependency,
    path: str = Query(min_length=1),
) -> dict[str, str] | JSONResponse:
    try:
        scope, queen_id, filename = _parse_path(path)
        deleted = await runtime.memory_store.delete(scope, filename, queen_id)
    except ValueError as error:
        return error_response(400, "INVALID_MEMORY_PATH", str(error))
    if not deleted:
        return error_response(404, "MEMORY_NOT_FOUND", "记忆不存在")
    return {"deleted": path}


__all__ = ["router"]
