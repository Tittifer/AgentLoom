"""Tests for persistent message redaction and truncation."""

from agentloom.colony.message_safety import TRUNCATION_MARKER, sanitize_json, sanitize_text


def test_message_safety_redacts_common_secret_shapes() -> None:
    result = sanitize_text("Authorization: Bearer abc.def token=secret-value sk-abcdefgh")
    assert "abc.def" not in result
    assert "secret-value" not in result
    assert "sk-abcdefgh" not in result
    assert result.count("[REDACTED]") == 3


def test_message_safety_sanitizes_json_and_truncates() -> None:
    assert sanitize_json({"api-key": "value", "nested": {"password": "value"}}) == {
        "api-key": "[REDACTED]",
        "nested": {"password": "[REDACTED]"},
    }
    result = sanitize_text("x" * 100, maximum=30)
    assert len(result) == 30
    assert result.endswith(TRUNCATION_MARKER)
