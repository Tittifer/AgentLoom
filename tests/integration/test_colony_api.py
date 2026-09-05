"""Local-storage integration tests for the Colony HTTP workflow."""

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from agentloom.colony.schemas import ColonyRead, ColonySnapshot, MessageRead, SessionRead
from agentloom.config import Settings
from agentloom.main import create_app


@pytest.fixture
async def colony_client(tmp_path: Path) -> AsyncIterator[tuple[AsyncClient, str]]:
    app = create_app(Settings(environment="test", log_level="WARNING", storage_root=tmp_path))
    prefix = f"Colony test {uuid4().hex}"
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            yield client, prefix


async def test_colony_api_creates_chats_and_lists(colony_client: tuple[AsyncClient, str]) -> None:
    client, prefix = colony_client
    created_response = await client.post(
        "/api/colonies",
        json={"name": prefix, "description": "集成测试", "queen_id": "general"},
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

    snapshot = ColonySnapshot.model_validate(
        (await client.get(f"/api/colonies/{colony.id}")).json()
    )
    for _ in range(30):
        if snapshot.queen_session.status == "idle":
            break
        await asyncio.sleep(0.02)
        snapshot = ColonySnapshot.model_validate(
            (await client.get(f"/api/colonies/{colony.id}")).json()
        )
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


async def test_first_message_names_an_untitled_colony(
    colony_client: tuple[AsyncClient, str],
) -> None:
    client, prefix = colony_client
    created_response = await client.post(
        "/api/colonies",
        json={"name": "新会话", "description": "", "queen_id": "general"},
    )
    colony = ColonyRead.model_validate(created_response.json())
    first_message = f"{prefix} 请制定完整计划"
    try:
        response = await client.post(
            f"/api/sessions/{colony.queen_session_id}/messages",
            json={"content": first_message},
        )
        assert response.status_code == 202
        snapshot = ColonySnapshot.model_validate(
            (await client.get(f"/api/colonies/{colony.id}")).json()
        )
        assert snapshot.colony.name == first_message[:32] + "…"
    finally:
        await client.delete(f"/api/colonies/{colony.id}")


async def test_one_queen_owns_multiple_isolated_sessions(
    colony_client: tuple[AsyncClient, str],
) -> None:
    client, prefix = colony_client
    queens = (await client.get("/api/queens")).json()
    assert [queen["id"] for queen in queens] == ["general"]

    colonies: list[ColonyRead] = []
    for suffix in ("A", "B"):
        response = await client.post(
            "/api/colonies",
            json={"name": f"{prefix}-{suffix}", "queen_id": "general"},
        )
        assert response.status_code == 201
        colonies.append(ColonyRead.model_validate(response.json()))

    first_session_id = colonies[0].queen_session_id
    second_session_id = colonies[1].queen_session_id
    assert first_session_id is not None and second_session_id is not None
    await client.post(
        f"/api/sessions/{first_session_id}/messages",
        json={"content": "只属于第一条会话"},
    )
    second_messages = await client.get(f"/api/sessions/{second_session_id}/messages")
    assert second_messages.json() == []

    sessions_response = await client.get("/api/queens/general/sessions")
    assert sessions_response.status_code == 200
    sessions = [SessionRead.model_validate(item) for item in sessions_response.json()]
    assert {session.id for session in sessions} == {first_session_id, second_session_id}
    assert all(session.queen_id == "general" for session in sessions)

    for colony in colonies:
        await client.delete(f"/api/colonies/{colony.id}")


async def test_custom_queen_supplies_colony_identity_and_default_model(
    colony_client: tuple[AsyncClient, str],
) -> None:
    client, prefix = colony_client
    queen_payload: dict[str, object] = {
        "id": "travel",
        "name": "旅行 Queen",
        "description": "旅行规划",
        "system_prompt": "你是专业旅行规划师。",
        "default_model": "mock/travel",
        "settings": {},
    }
    queen_response = await client.post("/api/queens", json=queen_payload)
    assert queen_response.status_code == 201
    duplicate = await client.post("/api/queens", json=queen_payload)
    assert duplicate.status_code == 409

    colony_response = await client.post(
        "/api/colonies",
        json={"name": prefix, "queen_id": "travel"},
    )
    assert colony_response.status_code == 201
    colony = ColonyRead.model_validate(colony_response.json())
    assert colony.queen_id == "travel"
    assert colony.model == "mock/travel"
    await client.delete(f"/api/colonies/{colony.id}")

    missing = await client.post(
        "/api/colonies",
        json={"name": prefix, "queen_id": "missing"},
    )
    assert missing.status_code == 404
    assert missing.json()["code"] == "QUEEN_NOT_FOUND"
