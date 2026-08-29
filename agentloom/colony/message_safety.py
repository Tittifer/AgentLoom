"""Secret redaction and storage limits for persistent Colony messages."""

import re

from pydantic import JsonValue

TRUNCATION_MARKER = "\n[TRUNCATED]"
DEFAULT_MAX_CONTENT_CHARS = 20_000
SENSITIVE_KEYS = frozenset({"api_key", "apikey", "authorization", "password", "secret", "token"})
SECRET_PATTERNS = (
    re.compile(r"(?i)(bearer\s+)[a-z0-9._~+/=-]+"),
    re.compile(r"(?i)\bsk-[a-z0-9_-]{8,}\b"),
    re.compile(r"(?i)((?:api[_-]?key|password|secret|token)\s*[:=]\s*)[^\s,;]+"),
)


def sanitize_text(value: str, maximum: int = DEFAULT_MAX_CONTENT_CHARS) -> str:
    redacted = value
    for pattern in SECRET_PATTERNS:
        if pattern.groups:
            redacted = pattern.sub(r"\1[REDACTED]", redacted)
        else:
            redacted = pattern.sub("[REDACTED]", redacted)
    if len(redacted) <= maximum:
        return redacted
    retained = max(0, maximum - len(TRUNCATION_MARKER))
    return redacted[:retained] + TRUNCATION_MARKER


def sanitize_json(value: JsonValue) -> JsonValue:
    if isinstance(value, dict):
        result: dict[str, JsonValue] = {}
        for key, item in value.items():
            normalized_key = key.lower().replace("-", "_")
            result[key] = "[REDACTED]" if normalized_key in SENSITIVE_KEYS else sanitize_json(item)
        return result
    if isinstance(value, list):
        return [sanitize_json(item) for item in value]
    if isinstance(value, str):
        return sanitize_text(value)
    return value


__all__ = [
    "DEFAULT_MAX_CONTENT_CHARS",
    "TRUNCATION_MARKER",
    "sanitize_json",
    "sanitize_text",
]
