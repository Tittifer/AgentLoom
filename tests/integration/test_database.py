"""PostgreSQL connectivity integration tests."""

from sqlalchemy import text

from agentloom.config import Settings
from agentloom.db.session import DatabaseSessionManager
from agentloom.main import create_app


async def test_database_connection() -> None:
    settings = Settings()
    database = DatabaseSessionManager(settings.database_url)

    try:
        async with database.session_factory() as session:
            result = await session.execute(text("SELECT 1"))
    finally:
        await database.dispose()

    assert result.scalar_one() == 1


async def test_application_lifespan_checks_database() -> None:
    app = create_app(Settings(environment="test", log_level="WARNING"))

    async with app.router.lifespan_context(app):
        assert isinstance(app.state.database, DatabaseSessionManager)
