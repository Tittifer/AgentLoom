"""FastAPI application entry point."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from agentloom.api.routes import colony_router, queen_router
from agentloom.api.schemas import HealthResponse
from agentloom.bootstrap import create_colony_runtime
from agentloom.colony.notifier import ColonyEventNotifier
from agentloom.config import Settings, get_settings
from agentloom.logging import configure_logging
from agentloom.storage import LocalColonyStore


async def health() -> HealthResponse:
    """Report whether the API process is available."""

    return HealthResponse(status="ok")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create an application instance with explicit runtime settings."""

    app_settings = settings or get_settings()
    configure_logging(app_settings.log_level)
    logger = structlog.get_logger(__name__)
    storage = LocalColonyStore(app_settings.storage_root)
    event_notifier = ColonyEventNotifier()
    colony_runtime = create_colony_runtime(storage, event_notifier, app_settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
        try:
            await storage.initialize()
        except Exception:
            logger.exception("storage_initialization_failed")
            await storage.close()
            raise

        logger.info("local_storage_ready", root=str(storage.root))
        logger.info(
            "application_started",
            environment=app_settings.environment,
            version=app_settings.app_version,
        )
        try:
            await colony_runtime.start()
            yield
        finally:
            try:
                await colony_runtime.stop()
            finally:
                await storage.close()
                logger.info("application_stopped")

    application = FastAPI(
        title=app_settings.app_name,
        version=app_settings.app_version,
        lifespan=lifespan,
    )
    application.state.storage = storage
    application.state.colony_event_notifier = event_notifier
    application.state.colony_runtime = colony_runtime
    application.include_router(colony_router, prefix="/api")
    application.include_router(queen_router, prefix="/api")
    application.add_api_route(
        "/health",
        health,
        methods=["GET"],
        response_model=HealthResponse,
        tags=["system"],
    )

    return application


app = create_app()
