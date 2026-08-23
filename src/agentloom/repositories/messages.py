"""Visible agent-message persistence with redaction and size limits."""

import re
from collections.abc import Mapping, Sequence
from uuid import UUID

from pydantic import JsonValue, TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from agentloom.db.base import utc_now
from agentloom.db.models.message import AgentMessageModel
from agentloom.llm.base import MessageRole
from agentloom.runtime.run import AgentMessageRead

JSON_OBJECT_LIST_ADAPTER = TypeAdapter(list[dict[str, JsonValue]])
TRUNCATION_MARKER = "\n[TRUNCATED]"
DEFAULT_MAX_CONTENT_CHARS = 20_000
SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "password",
        "secret",
        "token",
    }
)
SECRET_PATTERNS = (
    re.compile(r"(?i)(bearer\s+)[a-z0-9._~+/=-]+"),
    re.compile(r"(?i)\bsk-[a-z0-9_-]{8,}\b"),
    re.compile(r"(?i)((?:api[_-]?key|password|secret|token)\s*[:=]\s*)[^\s,;]+"),
)


class MessageRepository:
    """Append model-visible messages without storing common secret forms."""

    def __init__(
        self, session: AsyncSession, max_content_chars: int = DEFAULT_MAX_CONTENT_CHARS
    ) -> None:
        self._session = session
        self._max_content_chars = max_content_chars

    async def create(
        self,
        node_run_id: UUID,
        role: MessageRole,
        content: str,
        tool_calls: Sequence[Mapping[str, object]] = (),
    ) -> AgentMessageRead:
        """Sanitize and flush one visible message in the caller's transaction."""

        raw_calls = JSON_OBJECT_LIST_ADAPTER.validate_python(
            [dict(tool_call) for tool_call in tool_calls]
        )
        sanitized_calls = [_sanitize_json(tool_call) for tool_call in raw_calls]
        validated_calls = JSON_OBJECT_LIST_ADAPTER.validate_python(sanitized_calls)
        message = AgentMessageModel(
            node_run_id=node_run_id,
            role=role,
            content=_truncate(_redact_text(content), self._max_content_chars),
            tool_calls=validated_calls,
            created_at=utc_now(),
        )
        self._session.add(message)
        await self._session.flush()
        return AgentMessageRead(
            id=message.id,
            node_run_id=message.node_run_id,
            role=message.role,
            content=message.content,
            tool_calls=validated_calls,
            created_at=message.created_at,
        )


def _redact_text(value: str) -> str:
    redacted = value
    for pattern in SECRET_PATTERNS:
        if pattern.groups:
            redacted = pattern.sub(r"\1[REDACTED]", redacted)
        else:
            redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


def _truncate(value: str, maximum: int) -> str:
    if len(value) <= maximum:
        return value
    retained = max(0, maximum - len(TRUNCATION_MARKER))
    return value[:retained] + TRUNCATION_MARKER


def _sanitize_json(value: JsonValue) -> JsonValue:
    if isinstance(value, dict):
        result: dict[str, JsonValue] = {}
        for key, item in value.items():
            normalized_key = key.lower().replace("-", "_")
            result[key] = "[REDACTED]" if normalized_key in SENSITIVE_KEYS else _sanitize_json(item)
        return result
    if isinstance(value, list):
        return [_sanitize_json(item) for item in value]
    if isinstance(value, str):
        return _redact_text(value)
    return value


__all__ = ["DEFAULT_MAX_CONTENT_CHARS", "MessageRepository", "TRUNCATION_MARKER"]
