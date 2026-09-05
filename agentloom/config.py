"""Code-defined AgentLoom application settings."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseModel):
    """Runtime settings with no environment-file dependency."""

    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    storage_root: Path = Field(default=PROJECT_ROOT / ".agentloom")
    llm_timeout_seconds: float = Field(
        default=60,
        gt=0,
        le=600,
    )
    queen_max_turns: int = Field(
        default=20,
        ge=1,
        le=100,
    )
    max_concurrent_workers: int = Field(
        default=4,
        ge=1,
        le=50,
    )
    worker_timeout_seconds: int = Field(
        default=600,
        ge=1,
        le=3600,
    )
    app_name: str = "AgentLoom API"
    app_version: str = "0.1.0"


@lru_cache
def get_settings() -> Settings:
    """Return one code-defined settings instance for the process."""

    return Settings()
