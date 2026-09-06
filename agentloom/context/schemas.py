"""Validated contracts for context budgeting and persisted compaction state."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class ContextModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ContextPolicy(ContextModel):
    max_context_tokens: int = Field(default=128_000, ge=4_096)
    compaction_buffer_tokens: int = Field(default=8_000, ge=0)
    compaction_buffer_ratio: float = Field(default=0.4, ge=0, lt=1)
    compaction_summary_max_tokens: int = Field(default=8_192, ge=512)
    max_tool_result_chars: int = Field(default=20_000, ge=1_000)
    max_verbatim_user_messages: int = Field(default=40, ge=0)

    @property
    def trigger_tokens(self) -> int:
        reserved = self.compaction_buffer_tokens + int(
            self.max_context_tokens * self.compaction_buffer_ratio
        )
        return max(1_024, self.max_context_tokens - reserved)

    @classmethod
    def from_mapping(cls, values: Mapping[str, object]) -> ContextPolicy:
        fields = cls.model_fields
        return cls.model_validate({key: value for key, value in values.items() if key in fields})


class CompactionCheckpoint(ContextModel):
    schema_version: int = Field(default=1, ge=1)
    summary: str = Field(min_length=1)
    through_sequence: int = Field(ge=1)
    preserved_sequences: list[int] = Field(default_factory=lambda: list[int]())
    tokens_before: int = Field(ge=0)
    tokens_after: int = Field(ge=0)
    compacted_at: AwareDatetime


def checkpoint_now(
    summary: str,
    through_sequence: int,
    preserved_sequences: list[int],
    tokens_before: int,
    tokens_after: int,
    now: datetime,
) -> CompactionCheckpoint:
    return CompactionCheckpoint(
        summary=summary,
        through_sequence=through_sequence,
        preserved_sequences=preserved_sequences,
        tokens_before=tokens_before,
        tokens_after=tokens_after,
        compacted_at=now,
    )


__all__ = ["CompactionCheckpoint", "ContextPolicy", "checkpoint_now"]
