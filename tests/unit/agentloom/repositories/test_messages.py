"""Tests for visible message redaction and truncation."""

from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from agentloom.db.models.message import AgentMessageModel
from agentloom.repositories.messages import TRUNCATION_MARKER, MessageRepository


class RecordingSession:
    def __init__(self) -> None:
        self.message: AgentMessageModel | None = None

    def add(self, instance: object) -> None:
        assert isinstance(instance, AgentMessageModel)
        self.message = instance

    async def flush(self) -> None:
        assert self.message is not None
        self.message.id = uuid4()
        self.message.created_at = datetime.now(UTC)


async def test_create_redacts_and_truncates_visible_message_data() -> None:
    session = RecordingSession()
    repository = MessageRepository(cast(AsyncSession, session), max_content_chars=60)

    message = await repository.create(
        uuid4(),
        "assistant",
        "Authorization: Bearer abc.def token=secret-value " + "x" * 100,
        [
            {
                "id": "call-1",
                "arguments": {
                    "api_key": "secret",
                    "nested": [{"password": "secret"}, "Bearer token-value"],
                },
            }
        ],
    )

    assert "abc.def" not in message.content
    assert "secret-value" not in message.content
    assert len(message.content) == 60
    assert message.content.endswith(TRUNCATION_MARKER)
    assert message.tool_calls[0]["arguments"] == {
        "api_key": "[REDACTED]",
        "nested": [{"password": "[REDACTED]"}, "Bearer [REDACTED]"],
    }
