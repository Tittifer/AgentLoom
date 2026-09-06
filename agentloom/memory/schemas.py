"""Contracts for persisted and recalled memories."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MemoryScope = Literal["global", "queen"]
MemoryType = Literal["profile", "preference", "environment", "feedback"]


class MemoryModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MemoryRead(MemoryModel):
    path: str
    filename: str
    scope: MemoryScope
    queen_id: str | None = None
    name: str | None = None
    description: str | None = None
    type: MemoryType | None = None
    mtime: float = 0
    content: str | None = None


class MemoryWrite(MemoryModel):
    content: str = Field(min_length=1, max_length=4096)


__all__ = ["MemoryRead", "MemoryScope", "MemoryType", "MemoryWrite"]
