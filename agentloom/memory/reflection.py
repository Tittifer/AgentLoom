"""Background LLM agent that distils durable conversation memory."""

from __future__ import annotations

from collections.abc import Mapping

from agentloom.colony.schemas import MessageRead
from agentloom.llm.base import JsonValue, LLMMessage, LLMProvider, LLMRequest, ToolDefinition
from agentloom.memory.schemas import MemoryScope
from agentloom.memory.store import MAX_MEMORY_FILE_BYTES, MAX_MEMORY_FILES, LocalMemoryStore

REFLECTION_TOOLS = [
    ToolDefinition(
        name="list_memory_files",
        description="列出 global 或 queen 作用域中的长期记忆文件。",
        parameters={
            "type": "object",
            "properties": {"scope": {"type": "string", "enum": ["global", "queen"]}},
            "required": ["scope"],
            "additionalProperties": False,
        },
    ),
    ToolDefinition(
        name="read_memory_file",
        description="读取一个长期记忆 Markdown 文件。",
        parameters={
            "type": "object",
            "properties": {
                "scope": {"type": "string", "enum": ["global", "queen"]},
                "filename": {"type": "string"},
            },
            "required": ["scope", "filename"],
            "additionalProperties": False,
        },
    ),
    ToolDefinition(
        name="write_memory_file",
        description="创建或更新一个长期记忆 Markdown 文件。",
        parameters={
            "type": "object",
            "properties": {
                "scope": {"type": "string", "enum": ["global", "queen"]},
                "filename": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["scope", "filename", "content"],
            "additionalProperties": False,
        },
    ),
    ToolDefinition(
        name="delete_memory_file",
        description="删除重复、过时或错误的长期记忆文件。",
        parameters={
            "type": "object",
            "properties": {
                "scope": {"type": "string", "enum": ["global", "queen"]},
                "filename": {"type": "string"},
            },
            "required": ["scope", "filename"],
            "additionalProperties": False,
        },
    ),
]

SHORT_PROMPT = f"""你是后台 Reflection Agent，负责把对话中的长期稳定用户信息写成记忆。
global 保存所有 Queen 都需要的身份、偏好、环境和反馈；queen 保存当前 Queen 特有的稳定协作方式。
不要保存临时任务进度、代码片段、文件路径、工具结果或本轮一次性要求。
先查看已有文件，优先更新而不是重复创建；一条记忆只描述一个主题。
文件必须是 .md，并包含 name、description、type 的 YAML frontmatter。
type 只能是 profile、preference、environment、feedback。
用户身份统一写入 global:user-profile.md。
每个文件不超过 {MAX_MEMORY_FILE_BYTES} 字节，每个作用域不超过 {MAX_MEMORY_FILES} 个文件。
没有值得记忆的内容时直接说明原因，不调用写入工具。"""

LONG_PROMPT = f"""你是长期记忆整理 Agent。
检查 global 和当前 queen 的记忆，合并重复项、删除过时项、修正作用域并优化描述。
不要创造新事实。每个文件不超过 {MAX_MEMORY_FILE_BYTES} 字节，
每个作用域不超过 {MAX_MEMORY_FILES} 个文件。"""


class ReflectionAgent:
    def __init__(self, store: LocalMemoryStore, timeout_seconds: float) -> None:
        self._store = store
        self._timeout_seconds = timeout_seconds

    async def short_reflect(
        self,
        messages: list[MessageRead],
        queen_id: str,
        model: str,
        provider: LLMProvider,
    ) -> list[str]:
        lines: list[str] = []
        for message in messages[-50:]:
            if message.role not in {"user", "assistant"} or not message.content.strip():
                continue
            content = message.content.strip()
            if len(content) > 800:
                content = content[:800] + "…"
            lines.append(f"[{message.role}]: {content}")
        if not lines:
            return []
        return await self._run(SHORT_PROMPT, "\n".join(lines), queen_id, model, provider)

    async def long_reflect(
        self,
        queen_id: str,
        model: str,
        provider: LLMProvider,
    ) -> list[str]:
        manifest = await self._manifest(queen_id)
        if not manifest.strip():
            return []
        return await self._run(LONG_PROMPT, manifest, queen_id, model, provider)

    async def _run(
        self,
        system_prompt: str,
        user_content: str,
        queen_id: str,
        model: str,
        provider: LLMProvider,
    ) -> list[str]:
        messages = [
            LLMMessage(role="system", content=system_prompt),
            LLMMessage(role="user", content=user_content),
        ]
        changed: list[str] = []
        for _ in range(5):
            response = await provider.complete(
                LLMRequest(
                    model=model,
                    messages=messages,
                    tools=REFLECTION_TOOLS,
                    timeout_seconds=self._timeout_seconds,
                )
            )
            assistant = LLMMessage(
                role="assistant",
                content=response.content or "",
                reasoning_content=response.reasoning_content,
                tool_calls=response.tool_calls,
            )
            messages.append(assistant)
            if not response.tool_calls:
                break
            for call in response.tool_calls:
                result, modified = await self._execute(call.name, call.arguments, queen_id)
                if modified:
                    changed.append(modified)
                messages.append(LLMMessage(role="tool", content=result, tool_call_id=call.id))
        return changed

    async def _execute(
        self,
        name: str,
        arguments: Mapping[str, JsonValue],
        queen_id: str,
    ) -> tuple[str, str | None]:
        try:
            scope = _scope(arguments.get("scope"))
            filename = arguments.get("filename")
            if name == "list_memory_files":
                return await self._manifest(queen_id, scope), None
            if not isinstance(filename, str):
                raise ValueError("filename is required")
            target_queen = queen_id if scope == "queen" else None
            if name == "read_memory_file":
                item = await self._store.read(scope, filename, target_queen)
                return (item.content if item and item.content else "ERROR: memory not found"), None
            if name == "write_memory_file":
                content = arguments.get("content")
                if not isinstance(content, str):
                    raise ValueError("content is required")
                await self._store.write(scope, filename, content, target_queen)
                return "OK", f"{scope}:{filename}"
            if name == "delete_memory_file":
                deleted = await self._store.delete(scope, filename, target_queen)
                return ("OK" if deleted else "ERROR: memory not found"), (
                    f"{scope}:{filename}" if deleted else None
                )
            return f"ERROR: unknown tool {name}", None
        except (OSError, ValueError) as error:
            return f"ERROR: {error}", None

    async def _manifest(self, queen_id: str, only: MemoryScope | None = None) -> str:
        scopes: list[MemoryScope] = [only] if only else ["global", "queen"]
        blocks: list[str] = []
        for scope in scopes:
            items = await self._store.list(scope, queen_id if scope == "queen" else None)
            lines = [
                (
                    f"[{item.type or 'unknown'}] {item.filename}: "
                    f"{item.description or '(no description)'}"
                )
                for item in items
            ]
            blocks.append(f"## {scope}\n" + ("\n".join(lines) if lines else "(empty)"))
        return "\n\n".join(blocks)


def _scope(value: object) -> MemoryScope:
    if value not in {"global", "queen"}:
        raise ValueError("scope must be global or queen")
    return value  # type: ignore[return-value]


__all__ = ["ReflectionAgent"]
