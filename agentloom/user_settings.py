"""Global user-managed LLM settings persisted outside Queen profiles."""

from __future__ import annotations

from typing import Literal
from urllib.parse import urlsplit

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from agentloom.llm.model_routing import LLMProtocol

ResponseFormat = Literal["json_schema", "json_object"]


class UserSettingsModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class UserSettingsUpdate(UserSettingsModel):
    model: str = Field(min_length=1, max_length=200)
    base_url: str = Field(min_length=1, max_length=2_000)
    api_key: str = Field(min_length=1, max_length=10_000, repr=False)
    response_format: ResponseFormat = "json_schema"
    max_context_tokens: int = Field(default=128_000, ge=4_096, le=2_000_000)

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("base_url 必须是没有路径后缀的 HTTP(S) 服务地址")
        return f"{parsed.scheme}://{parsed.netloc}"


class UserSettingsRead(UserSettingsModel):
    configured: bool
    model: str | None = None
    protocol: LLMProtocol | None = None
    base_url: str | None = None
    api_key_configured: bool = False
    response_format: ResponseFormat = "json_schema"
    max_context_tokens: int = 128_000
    updated_at: AwareDatetime | None = None


class UserLLMRuntimeConfig(UserSettingsUpdate):
    protocol: LLMProtocol
    updated_at: AwareDatetime


def public_settings(config: UserLLMRuntimeConfig | None) -> UserSettingsRead:
    if config is None:
        return UserSettingsRead(configured=False)
    return UserSettingsRead(
        configured=True,
        model=config.model,
        protocol=config.protocol,
        base_url=config.base_url,
        api_key_configured=True,
        response_format=config.response_format,
        max_context_tokens=config.max_context_tokens,
        updated_at=config.updated_at,
    )


__all__ = [
    "ResponseFormat",
    "UserLLMRuntimeConfig",
    "UserSettingsRead",
    "UserSettingsUpdate",
    "public_settings",
]
