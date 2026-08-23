"""FastAPI application entry point."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from agentloom.api.routes import run_router, task_router
from agentloom.api.schemas import HealthResponse
from agentloom.bootstrap import create_run_scheduler
from agentloom.config import Settings, get_settings
from agentloom.db.session import DatabaseSessionManager
from agentloom.logging import configure_logging
from agentloom.services.event_service import RunEventNotifier


async def health() -> HealthResponse:
    """Report whether the API process is available."""

    return HealthResponse(status="ok")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create an application instance with explicit runtime settings."""

    app_settings = settings or get_settings()
    configure_logging(app_settings.log_level)
    logger = structlog.get_logger(__name__)
    database = DatabaseSessionManager(app_settings.database_url)
    event_notifier = RunEventNotifier()
    scheduler = create_run_scheduler(database, event_notifier, app_settings)

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
            await scheduler.start()
            yield
        finally:
            try:
                await scheduler.stop()
            finally:
                await database.dispose()
                logger.info("application_stopped")

    application = FastAPI(
        title=app_settings.app_name,
        version=app_settings.app_version,
        lifespan=lifespan,
    )
    application.state.database = database
    application.state.run_event_notifier = event_notifier
    application.state.run_scheduler = scheduler
    application.include_router(task_router, prefix="/api")
    application.include_router(run_router, prefix="/api")
    application.add_api_route(
        "/health",
        health,
        methods=["GET"],
        response_model=HealthResponse,
        tags=["system"],
    )

    return application


app = create_app()
