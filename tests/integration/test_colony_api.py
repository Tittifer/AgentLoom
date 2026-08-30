"""PostgreSQL integration tests for the Colony HTTP workflow."""

import asyncio
from collections.abc import AsyncIterator
from typing import cast
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from agentloom.colony.schemas import ColonyRead, ColonySnapshot, MessageRead
from agentloom.config import Settings
from agentloom.db.models.colony import ColonyModel
from agentloom.db.session import DatabaseSessionManager
from agentloom.main import create_app


@pytest.fixture
async def colony_client() -> AsyncIterator[tuple[AsyncClient, str]]:
    app = create_app(Settings(environment="test", log_level="WARNING"))
    database = cast(DatabaseSessionManager, app.state.database)
    prefix = f"Colony test {uuid4().hex}"
    async with app.router.lifespan_context(app):
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                yield client, prefix
        finally:
            async with database.session_factory.begin() as session:
                await session.execute(
                    delete(ColonyModel).where(ColonyModel.name.like(f"{prefix}%"))
                )


async def test_colony_api_creates_chats_and_lists(colony_client: tuple[AsyncClient, str]) -> None:
    client, prefix = colony_client
    created_response = await client.post(
        "/api/colonies",
        json={"name": prefix, "description": "集成测试", "queen_profile": "general"},
    )
    assert created_response.status_code == 201
    colony = ColonyRead.model_validate(created_response.json())
    assert colony.queen_session_id is not None

    message_response = await client.post(
        f"/api/sessions/{colony.queen_session_id}/messages",
        json={"content": "请分析这个目标"},
    )
    assert message_response.status_code == 202
    assert MessageRead.model_validate(message_response.json()).role == "user"

    messages: list[MessageRead] = []
    for _ in range(30):
        response = await client.get(f"/api/sessions/{colony.queen_session_id}/messages")
        messages = [MessageRead.model_validate(item) for item in response.json()]
        if any(item.role == "assistant" for item in messages):
            break
        await asyncio.sleep(0.02)
    assert [item.role for item in messages] == ["user", "assistant"]

    snapshot_response = await client.get(f"/api/colonies/{colony.id}")
    snapshot = ColonySnapshot.model_validate(snapshot_response.json())
    assert snapshot.queen_session.status == "idle"
    assert snapshot.workers == []
    list_response = await client.get("/api/colonies")
    assert any(item["id"] == str(colony.id) for item in list_response.json())

    delete_response = await client.delete(f"/api/colonies/{colony.id}")
    assert delete_response.status_code == 204
    assert (await client.get(f"/api/colonies/{colony.id}")).status_code == 404


async def test_colony_api_returns_standard_missing_errors(
    colony_client: tuple[AsyncClient, str],
) -> None:
    client, _ = colony_client
    missing = uuid4()
    colony_response = await client.get(f"/api/colonies/{missing}")
    delete_response = await client.delete(f"/api/colonies/{missing}")
    session_response = await client.get(f"/api/sessions/{missing}/messages")
    assert colony_response.status_code == 404
    assert colony_response.json()["code"] == "COLONY_NOT_FOUND"
    assert delete_response.status_code == 404
    assert delete_response.json()["code"] == "COLONY_NOT_FOUND"
    assert session_response.status_code == 404
    assert session_response.json()["code"] == "SESSION_NOT_FOUND"
