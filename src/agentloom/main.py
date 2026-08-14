"""FastAPI application entry point."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from agentloom.api.schemas import HealthResponse
from agentloom.config import Settings, get_settings
from agentloom.db.session import DatabaseSessionManager
from agentloom.logging import configure_logging


async def health() -> HealthResponse:
    """Report whether the API process is available."""

    return HealthResponse(status="ok")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create an application instance with explicit runtime settings."""

    app_settings = settings or get_settings()
    configure_logging(app_settings.log_level)
    logger = structlog.get_logger(__name__)
    database = DatabaseSessionManager(app_settings.database_url)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
        try:
            await database.check_connection()
        except Exception:
            logger.exception("database_connection_failed")
            await database.dispose()
            raise

        logger.info("database_connected")
        logger.info(
            "application_started",
            environment=app_settings.environment,
            version=app_settings.app_version,
        )
        try:
            yield
        finally:
            await database.dispose()
            logger.info("application_stopped")

    application = FastAPI(
        title=app_settings.app_name,
        version=app_settings.app_version,
        lifespan=lifespan,
    )
    application.state.database = database
    application.add_api_route(
        "/health",
        health,
        methods=["GET"],
        response_model=HealthResponse,
        tags=["system"],
    )

    return application


app = create_app()
