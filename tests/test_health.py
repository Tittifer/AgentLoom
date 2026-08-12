"""Health endpoint tests."""

from typing import cast

from httpx import ASGITransport, AsyncClient

from agentloom.config import Settings
from agentloom.main import create_app


async def test_health_returns_ok() -> None:
    app = create_app(Settings(environment="test", log_level="WARNING"))
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_openapi_contains_health_endpoint() -> None:
    app = create_app(Settings(environment="test", log_level="WARNING"))
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/openapi.json")

    assert response.status_code == 200
    payload = cast(dict[str, object], response.json())
    paths = cast(dict[str, object], payload["paths"])
    assert "/health" in paths
