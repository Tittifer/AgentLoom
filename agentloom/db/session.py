"""Asynchronous SQLAlchemy engine and session lifecycle."""

from collections.abc import AsyncIterator
from typing import cast

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


class DatabaseSessionManager:
    """Own the database engine and sessions for one application instance."""

    def __init__(self, database_url: str) -> None:
        self.engine: AsyncEngine = create_async_engine(
            database_url,
            pool_pre_ping=True,
        )
        self.session_factory = async_sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    async def check_connection(self) -> None:
        """Raise when PostgreSQL cannot accept a simple query."""

        async with self.engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

    async def dispose(self) -> None:
        """Close all pooled database connections."""

        await self.engine.dispose()


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Provide a transaction-ready session for one FastAPI request."""

    database = cast(DatabaseSessionManager, request.app.state.database)
    async with database.session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
