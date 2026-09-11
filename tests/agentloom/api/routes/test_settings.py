"""Unit tests for global user-settings route delegation."""

from typing import cast

from agentloom.api.routes.settings import get_user_settings, update_user_settings
from agentloom.colony.runtime import ColonyRuntime
from agentloom.user_settings import UserSettingsRead, UserSettingsUpdate


class FakeRuntime:
    async def get_user_settings(self) -> UserSettingsRead:
        return UserSettingsRead(configured=False)

    async def update_user_settings(
        self,
        payload: UserSettingsUpdate,
    ) -> UserSettingsRead:
        return UserSettingsRead(
            configured=True,
            model=payload.model,
            protocol="openai",
            base_url=payload.base_url,
            api_key_configured=True,
            response_format=payload.response_format,
            max_context_tokens=payload.max_context_tokens,
        )


async def test_settings_routes_delegate_to_runtime() -> None:
    runtime = cast(ColonyRuntime, FakeRuntime())
    assert await get_user_settings(runtime) == UserSettingsRead(configured=False)

    payload = UserSettingsUpdate(
        model="openai/gpt-5",
        base_url="https://api.openai.com",
        api_key="secret",
    )
    updated = await update_user_settings(payload, runtime)
    assert updated.model == "openai/gpt-5"
    assert updated.api_key_configured is True
