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
    database_url: str = Field(
        default="postgresql+asyncpg://agentloom:agentloom@localhost:15432/agentloom",
        validation_alias="AGENTLOOM_DATABASE_URL",
    )
    llm_provider: Literal["mock", "litellm"] = Field(
        default="mock",
        validation_alias="AGENTLOOM_LLM_PROVIDER",
    )
    llm_model: str = Field(
        default="mock/schema",
        min_length=1,
        validation_alias="AGENTLOOM_LLM_MODEL",
    )
    llm_response_format: Literal["json_schema", "json_object"] = Field(
        default="json_schema",
        validation_alias="AGENTLOOM_LLM_RESPONSE_FORMAT",
    )
    llm_timeout_seconds: float = Field(
        default=60,
        gt=0,
        le=600,
        validation_alias="AGENTLOOM_LLM_TIMEOUT_SECONDS",
    )
    queen_max_turns: int = Field(
        default=20,
        ge=1,
        le=100,
        validation_alias="AGENTLOOM_QUEEN_MAX_TURNS",
    )
    max_concurrent_workers: int = Field(
        default=4,
        ge=1,
        le=50,
        validation_alias="AGENTLOOM_MAX_CONCURRENT_WORKERS",
    )
    worker_timeout_seconds: int = Field(
        default=600,
        ge=1,
        le=3600,
        validation_alias="AGENTLOOM_WORKER_TIMEOUT_SECONDS",
    )
    app_name: str = "AgentLoom API"
    app_version: str = "0.1.0"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )


@lru_cache
def get_settings() -> Settings:
    """Return one immutable settings instance for the process."""

    return Settings()
