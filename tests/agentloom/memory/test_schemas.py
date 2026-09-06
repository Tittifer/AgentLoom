"""Memory contract tests."""

import pytest
from pydantic import ValidationError

from agentloom.memory.schemas import MemoryWrite


def test_memory_write_preserves_markdown_whitespace() -> None:
    payload = MemoryWrite(content="---\nname: 测试\n---\n\n正文\n")
    assert payload.content.endswith("\n")


def test_memory_write_rejects_empty_content() -> None:
    with pytest.raises(ValidationError):
        MemoryWrite(content="")
