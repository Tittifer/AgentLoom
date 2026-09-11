"""Small asynchronous client for one MCP server connection."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import Tool
from pydantic import JsonValue, TypeAdapter

JSON_VALUE: TypeAdapter[JsonValue] = TypeAdapter(JsonValue)


@dataclass(frozen=True)
class MCPServerConfig:
    """Configuration for a local stdio MCP server."""

    name: str
    command: str
    args: tuple[str, ...] = ()
    cwd: Path | None = None
    env: dict[str, str] = field(default_factory=lambda: {})
    timeout_seconds: float = 30


class MCPClientError(RuntimeError):
    """Base error raised by the MCP transport boundary."""


class MCPToolCallError(MCPClientError):
    """An MCP server rejected or failed one tool call."""


class MCPClient:
    """Own one persistent stdio MCP session and its discovered tools."""

    def __init__(self, config: MCPServerConfig) -> None:
        self.config = config
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None
        self._tools: tuple[Tool, ...] = ()
        self._call_lock = asyncio.Lock()

    @property
    def tools(self) -> tuple[Tool, ...]:
        return self._tools

    async def connect(self) -> None:
        if self._session is not None:
            return
        stack = AsyncExitStack()
        try:
            parameters = StdioServerParameters(
                command=self.config.command,
                args=list(self.config.args),
                cwd=self.config.cwd,
                env={**os.environ, **self.config.env},
                encoding="utf-8",
                encoding_error_handler="strict",
            )
            read_stream, write_stream = await stack.enter_async_context(
                stdio_client(parameters, errlog=sys.stderr)
            )
            session = await stack.enter_async_context(
                ClientSession(
                    read_stream,
                    write_stream,
                    read_timeout_seconds=timedelta(seconds=self.config.timeout_seconds),
                )
            )
            await session.initialize()
            discovered = await session.list_tools()
        except BaseException:
            await stack.aclose()
            raise
        self._stack = stack
        self._session = session
        self._tools = tuple(discovered.tools)

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> JsonValue:
        session = self._session
        if session is None:
            raise MCPClientError(f"MCP server {self.config.name} is not connected")
        try:
            async with self._call_lock:
                result = await session.call_tool(
                    name,
                    arguments=arguments,
                    read_timeout_seconds=timedelta(seconds=self.config.timeout_seconds),
                )
        except Exception as error:
            raise MCPClientError(
                f"MCP call {name} on {self.config.name} failed: {error}"
            ) from error
        if result.isError:
            message = "\n".join(str(getattr(item, "text", "")) for item in result.content).strip()
            raise MCPToolCallError(message or f"MCP tool {name} failed")
        if result.structuredContent is not None:
            return JSON_VALUE.validate_python(result.structuredContent)
        text = "\n".join(str(getattr(item, "text", "")) for item in result.content).strip()
        if not text:
            return None
        try:
            return JSON_VALUE.validate_python(json.loads(text))
        except json.JSONDecodeError:
            return text

    async def close(self) -> None:
        stack = self._stack
        self._stack = None
        self._session = None
        self._tools = ()
        if stack is not None:
            await stack.aclose()


__all__ = [
    "MCPClient",
    "MCPClientError",
    "MCPServerConfig",
    "MCPToolCallError",
]
