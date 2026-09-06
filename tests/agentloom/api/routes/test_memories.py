"""Memory management route tests."""

from pathlib import Path

from httpx import ASGITransport, AsyncClient

from agentloom.config import Settings
from agentloom.llm.mock import SchemaMockLLMProvider
from agentloom.main import create_app

DOCUMENT = "---\nname: 用户偏好\ndescription: 回复风格\ntype: preference\n---\n\n保持简洁。\n"


async def test_memory_crud_and_path_validation(tmp_path: Path) -> None:
    app = create_app(
        Settings(environment="test", log_level="WARNING", storage_root=tmp_path),
        SchemaMockLLMProvider(),
    )
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            created = await client.post(
                "/api/memories/file",
                params={"path": "global/style.md"},
                json={"content": DOCUMENT},
            )
            assert created.status_code == 201
            assert created.json()["type"] == "preference"
            assert (await client.get("/api/memories")).json()[0]["path"] == "global/style.md"

            fetched = await client.get("/api/memories/file", params={"path": "global/style.md"})
            assert fetched.json()["content"] == DOCUMENT
            rejected = await client.get("/api/memories/file", params={"path": "../profile.yaml"})
            assert rejected.status_code == 400
            deleted = await client.delete("/api/memories/file", params={"path": "global/style.md"})
            assert deleted.status_code == 200
            assert deleted.json() == {"deleted": "global/style.md"}
