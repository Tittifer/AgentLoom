"""Lifecycle and routing for AgentLoom MCP tool servers."""

from __future__ import annotations

import asyncio
import sys
from typing import Any

import structlog
from pydantic import JsonValue

from agentloom.config import PROJECT_ROOT
from agentloom.tools.mcp.adapter import MCPToolAdapter
from agentloom.tools.mcp.client import MCPClient, MCPClientError, MCPServerConfig


def builtin_server_config() -> MCPServerConfig:
    """Return the code-defined bundled tool server configuration."""

    return MCPServerConfig(
        name="agentloom_builtin",
        command=sys.executable,
        args=("-m", "agentloom.tools.servers.builtin"),
        cwd=PROJECT_ROOT,
    )


class MCPManager:
    """Start configured servers once and route calls to their live clients."""

    def __init__(self, configs: list[MCPServerConfig]) -> None:
        self._configs = tuple(configs)
        self._clients: dict[str, MCPClient] = {}
        self._started = False
        self._lock = asyncio.Lock()
        self._logger = structlog.get_logger(__name__)

    async def start(self) -> None:
        async with self._lock:
            if self._started:
                return
            self._started = True
            for config in self._configs:
                client = MCPClient(config)
                try:
                    await client.connect()
                except Exception as error:
                    self._logger.error(
                        "mcp_server_start_failed",
                        server=config.name,
                        error_type=type(error).__name__,
                        error=str(error),
                    )
                    continue
                self._clients[config.name] = client
                self._logger.info(
                    "mcp_server_ready",
                    server=config.name,
                    tool_count=len(client.tools),
                )

    def tool_adapters(self) -> list[MCPToolAdapter]:
        return [
            MCPToolAdapter(self, server_name, tool)
            for server_name, client in self._clients.items()
            for tool in client.tools
        ]

    async def call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> JsonValue:
        client = self._clients.get(server_name)
        if client is None:
            raise MCPClientError(f"MCP server {server_name} is not connected")
        return await client.call_tool(tool_name, arguments)

    async def close(self) -> None:
        async with self._lock:
            clients = tuple(reversed(tuple(self._clients.values())))
            self._clients.clear()
            self._started = False
            for client in clients:
                try:
                    await client.close()
                except Exception as error:
                    self._logger.error(
                        "mcp_server_stop_failed",
                        server=client.config.name,
                        error_type=type(error).__name__,
                        error=str(error),
                    )


__all__ = ["MCPManager", "MCPServerConfig", "builtin_server_config"]
