"""Typed application configuration loaded from environment variables."""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings for the AgentLoom API."""

    environment: Literal["development", "test", "production"] = Field(
        default="development",
        validation_alias="AGENTLOOM_ENV",
    )
    log_level: str = Field(default="INFO", validation_alias="AGENTLOOM_LOG_LEVEL")
    app_name: str = "AgentLoom API"
    app_version: str = "0.1.0"

    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )


@lru_cache
def get_settings() -> Settings:
    """Return one immutable settings instance for the process."""

    return Settings()
