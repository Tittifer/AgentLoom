"""FastAPI application entry point."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from pydantic import BaseModel

from agentloom.config import Settings, get_settings
from agentloom.logging import configure_logging


class HealthResponse(BaseModel):
    """Response returned by the health endpoint."""

    status: str


async def health() -> HealthResponse:
    """Report whether the API process is available."""

    return HealthResponse(status="ok")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create an application instance with explicit runtime settings."""

    app_settings = settings or get_settings()
    configure_logging(app_settings.log_level)
    logger = structlog.get_logger(__name__)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
        logger.info(
            "application_started",
            environment=app_settings.environment,
            version=app_settings.app_version,
        )
        yield
        logger.info("application_stopped")

    application = FastAPI(
        title=app_settings.app_name,
        version=app_settings.app_version,
        lifespan=lifespan,
    )
    application.add_api_route(
        "/health",
        health,
        methods=["GET"],
        response_model=HealthResponse,
        tags=["system"],
    )

    return application


app = create_app()
