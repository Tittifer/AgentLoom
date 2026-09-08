"""Global user settings endpoints."""

from fastapi import APIRouter

from agentloom.api.routes.colonies import RuntimeDependency
from agentloom.user_settings import UserSettingsRead, UserSettingsUpdate

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=UserSettingsRead)
async def get_user_settings(runtime: RuntimeDependency) -> UserSettingsRead:
    return await runtime.get_user_settings()


@router.put("", response_model=UserSettingsRead)
async def update_user_settings(
    payload: UserSettingsUpdate,
    runtime: RuntimeDependency,
) -> UserSettingsRead:
    return await runtime.update_user_settings(payload)


__all__ = ["router"]
