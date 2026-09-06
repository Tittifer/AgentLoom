"""Select and format memories relevant to one Queen request."""

from __future__ import annotations

import json
import time
from datetime import timedelta
from typing import cast

import structlog

from agentloom.llm.base import JsonObject, LLMMessage, LLMProvider, LLMRequest
from agentloom.memory.schemas import MemoryRead
from agentloom.memory.store import LocalMemoryStore

SELECT_SCHEMA: JsonObject = {
    "type": "object",
    "properties": {
        "selected_memories": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 3,
        }
    },
    "required": ["selected_memories"],
    "additionalProperties": False,
}

SELECT_PROMPT = """你负责为 Queen 选择与用户最新请求明确相关的长期记忆。
只返回清单中存在的文件名，最多选择 3 个；不确定时不要选择。
必须输出 JSON 对象：{"selected_memories": ["file.md"]}。"""


class RecallSelector:
    def __init__(self, store: LocalMemoryStore, timeout_seconds: float = 3.0) -> None:
        self._store = store
        self._timeout_seconds = timeout_seconds
        self._logger = structlog.get_logger(__name__)

    async def recall(
        self,
        query: str,
        queen_id: str,
        model: str,
        provider: LLMProvider,
    ) -> str:
        global_items = await self._store.list("global")
        queen_items = await self._store.list("queen", queen_id)
        if not global_items and not queen_items:
            return ""
        global_selected = await self._select(query, global_items, model, provider)
        queen_selected = await self._select(query, queen_items, model, provider)
        blocks = [
            await self._format_scope("Global Memories", "global", None, global_selected),
            await self._format_scope(
                f"Queen Memories: {queen_id}",
                "queen",
                queen_id,
                queen_selected,
            ),
        ]
        return "\n\n".join(block for block in blocks if block)

    async def _select(
        self,
        query: str,
        items: list[MemoryRead],
        model: str,
        provider: LLMProvider,
    ) -> list[str]:
        if not items:
            return []
        pinned = [item.filename for item in items if item.type == "profile"][:3]
        manifest = "\n".join(
            f"[{item.type or 'unknown'}] {item.filename}: {item.description or '(no description)'}"
            for item in items
        )
        request = LLMRequest(
            model=model,
            messages=[
                LLMMessage(role="system", content=SELECT_PROMPT),
                LLMMessage(
                    role="user",
                    content=f"## 用户请求\n{query}\n\n## 可用记忆\n{manifest}",
                ),
            ],
            response_schema=SELECT_SCHEMA,
            timeout_seconds=self._timeout_seconds,
            purpose="recall",
        )
        try:
            response = await provider.complete(request)
            data = response.structured_output or _parse_json_object(response.content or "")
            raw_selected = data.get("selected_memories", []) if data else []
            aliases = {item.filename: item.filename for item in items}
            aliases.update({item.filename.removesuffix(".md"): item.filename for item in items})
            selected = list(pinned)
            if isinstance(raw_selected, list):
                for raw in raw_selected:
                    matched = aliases.get(raw) if isinstance(raw, str) else None
                    if matched and matched not in selected:
                        selected.append(matched)
            return selected[:3]
        except Exception as error:
            self._logger.warning(
                "memory_recall_failed",
                error_type=type(error).__name__,
                error=str(error),
            )
            return pinned

    async def _format_scope(
        self,
        label: str,
        scope: str,
        queen_id: str | None,
        filenames: list[str],
    ) -> str:
        blocks: list[str] = []
        for filename in filenames:
            item = await self._store.read(scope, filename, queen_id)  # type: ignore[arg-type]
            if item is None or item.content is None:
                continue
            age_seconds = max(0, time.time() - item.mtime)
            age = (
                f"（{timedelta(seconds=int(age_seconds)).days} 天前）"
                if age_seconds > 172800
                else ""
            )
            blocks.append(f"### {filename}{age}\n\n{item.content.strip()}")
        if not blocks:
            return ""
        return f"--- {label} ---\n\n" + "\n\n---\n\n".join(blocks) + f"\n\n--- End {label} ---"


def _parse_json_object(raw: str) -> JsonObject | None:
    try:
        value = cast(object, json.loads(raw))
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            value = cast(object, json.loads(raw[start : end + 1]))
        except json.JSONDecodeError:
            return None
    return cast(JsonObject, value) if isinstance(value, dict) else None


__all__ = ["RecallSelector"]
