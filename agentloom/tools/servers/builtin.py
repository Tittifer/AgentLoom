"""Bundled read-only tools exposed through a local MCP stdio server."""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from mcp.server.fastmcp import FastMCP

MAX_FILE_BYTES = 1_000_000
MAX_FETCH_BYTES = 250_000
MAX_REDIRECTS = 3
TEXT_CONTENT_TYPES = (
    "application/json",
    "application/xml",
    "application/xhtml+xml",
    "text/",
)

mcp = FastMCP("agentloom-builtin-tools", log_level="ERROR")


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._ignored_depth = 0
        self._in_title = False
        self.parts: list[str] = []
        self.title_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in {"script", "style", "noscript"}:
            self._ignored_depth += 1
        elif tag == "title":
            self._in_title = True
        elif tag in {"br", "p", "div", "li", "section", "article", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._ignored_depth:
            self._ignored_depth -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        self.parts.append(data)
        if self._in_title:
            self.title_parts.append(data)


def _workspace_path(workspace_root: str, relative_path: str = ".") -> tuple[Path, Path]:
    root = Path(workspace_root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Workspace root is not a directory")
    requested = Path(relative_path)
    if requested.is_absolute() or ".." in requested.parts:
        raise ValueError("Path must stay inside the current session workspace")
    resolved = (root / requested).resolve(strict=False)
    if not resolved.is_relative_to(root):
        raise ValueError("Path resolves outside the current session workspace")
    return root, resolved


def _safe_workspace_files(workspace_root: str, pattern: str) -> list[tuple[Path, Path]]:
    root, _ = _workspace_path(workspace_root)
    candidate = Path(pattern)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError("Glob pattern must stay inside the current session workspace")
    files: list[tuple[Path, Path]] = []
    for path in root.glob(pattern):
        try:
            resolved = path.resolve(strict=True)
        except OSError:
            continue
        if resolved.is_relative_to(root) and resolved.is_file():
            files.append((path, resolved))
    return files


def _normalize_text(value: str) -> str:
    lines = [re.sub(r"\s+", " ", line).strip() for line in value.splitlines()]
    return "\n".join(line for line in lines if line)


async def _validate_public_url(url: str) -> None:
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("URL must be a public HTTP(S) address without embedded credentials")
    hostname = parsed.hostname.rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith(".localhost") or hostname.endswith(".local"):
        raise ValueError("Local and private network addresses are not allowed")
    try:
        addresses = await asyncio.to_thread(
            socket.getaddrinfo,
            hostname,
            parsed.port or (443 if parsed.scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as error:
        raise ValueError(f"Could not resolve URL host: {hostname}") from error
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global:
            raise ValueError("Local and private network addresses are not allowed")


@mcp.tool()
def get_current_time(timezone: str = "UTC") -> dict[str, str]:
    """Return the current date and time in an IANA timezone."""

    try:
        zone = ZoneInfo(timezone)
    except ZoneInfoNotFoundError as error:
        raise ValueError(f"Unknown IANA timezone: {timezone}") from error
    value = datetime.now(zone)
    return {
        "timezone": timezone,
        "iso8601": value.isoformat(),
        "utc": datetime.now(UTC).isoformat(),
    }


@mcp.tool()
def workspace_glob(
    pattern: str,
    workspace_root: str,
    max_results: int = 200,
) -> dict[str, object]:
    """List files matching a glob inside the current session workspace."""

    if not pattern or len(pattern) > 500:
        raise ValueError("Pattern must contain 1-500 characters")
    limit = max(1, min(max_results, 500))
    root, _ = _workspace_path(workspace_root)
    paths = sorted(
        path.relative_to(root).as_posix()
        for path, _ in _safe_workspace_files(workspace_root, pattern)
    )
    return {
        "pattern": pattern,
        "files": paths[:limit],
        "truncated": len(paths) > limit,
    }


@mcp.tool()
def workspace_read(
    path: str,
    workspace_root: str,
    start_line: int = 1,
    max_lines: int = 400,
) -> dict[str, object]:
    """Read UTF-8 text from a file inside the current session workspace."""

    if start_line < 1:
        raise ValueError("start_line must be at least 1")
    limit = max(1, min(max_lines, 1_000))
    root, resolved = _workspace_path(workspace_root, path)
    if not resolved.is_file():
        raise ValueError(f"Workspace file does not exist: {path}")
    if resolved.stat().st_size > MAX_FILE_BYTES:
        raise ValueError(f"Workspace file exceeds {MAX_FILE_BYTES} bytes")
    try:
        lines = resolved.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise ValueError(f"Workspace file is not UTF-8 text: {path}") from error
    start = min(start_line - 1, len(lines))
    selected = lines[start : start + limit]
    return {
        "path": resolved.relative_to(root).as_posix(),
        "start_line": start + 1,
        "end_line": start + len(selected),
        "total_lines": len(lines),
        "content": "\n".join(selected),
        "truncated": start + len(selected) < len(lines),
    }


@mcp.tool()
def workspace_search(
    query: str,
    workspace_root: str,
    pattern: str = "**/*",
    max_results: int = 100,
    case_sensitive: bool = False,
) -> dict[str, object]:
    """Search UTF-8 workspace files and return matching lines."""

    if not query or len(query) > 500:
        raise ValueError("Query must contain 1-500 characters")
    limit = max(1, min(max_results, 500))
    root, _ = _workspace_path(workspace_root)
    needle = query if case_sensitive else query.casefold()
    matches: list[dict[str, object]] = []
    scanned_files = 0
    for _, resolved in sorted(
        _safe_workspace_files(workspace_root, pattern),
        key=lambda item: item[0].as_posix(),
    ):
        if resolved.stat().st_size > MAX_FILE_BYTES:
            continue
        try:
            lines = resolved.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        scanned_files += 1
        for line_number, line in enumerate(lines, start=1):
            haystack = line if case_sensitive else line.casefold()
            if needle not in haystack:
                continue
            matches.append(
                {
                    "path": resolved.relative_to(root).as_posix(),
                    "line": line_number,
                    "text": line[:1_000],
                }
            )
            if len(matches) >= limit:
                return {
                    "query": query,
                    "matches": matches,
                    "scanned_files": scanned_files,
                    "truncated": True,
                }
    return {
        "query": query,
        "matches": matches,
        "scanned_files": scanned_files,
        "truncated": False,
    }


@mcp.tool()
async def web_fetch(url: str, max_chars: int = 20_000) -> dict[str, object]:
    """Fetch readable text from a public HTTP(S) webpage with bounded output."""

    limit = max(1_000, min(max_chars, 50_000))
    current_url = url
    timeout = httpx.Timeout(10, connect=5)
    async with httpx.AsyncClient(
        timeout=timeout,
        headers={"User-Agent": "AgentLoom/0.1 (+local MCP web_fetch)"},
    ) as client:
        for redirect_count in range(MAX_REDIRECTS + 1):
            await _validate_public_url(current_url)
            async with client.stream("GET", current_url, follow_redirects=False) as response:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location or redirect_count >= MAX_REDIRECTS:
                        raise ValueError("Web request exceeded the redirect limit")
                    current_url = urljoin(current_url, location)
                    continue
                response.raise_for_status()
                content_type = response.headers.get("content-type", "").lower()
                if content_type and not any(
                    allowed in content_type for allowed in TEXT_CONTENT_TYPES
                ):
                    raise ValueError(f"Unsupported web content type: {content_type}")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_FETCH_BYTES:
                        break
                encoding = response.encoding or "utf-8"
                decoded = bytes(body[:MAX_FETCH_BYTES]).decode(encoding, errors="replace")
                title = ""
                if "text/html" in content_type:
                    extractor = _HTMLTextExtractor()
                    extractor.feed(decoded)
                    text = _normalize_text("".join(extractor.parts))
                    title = _normalize_text("".join(extractor.title_parts))
                else:
                    text = _normalize_text(decoded)
                return {
                    "url": str(response.url),
                    "status_code": response.status_code,
                    "content_type": content_type,
                    "title": title,
                    "text": text[:limit],
                    "truncated": len(body) > MAX_FETCH_BYTES or len(text) > limit,
                }
    raise ValueError("Web request failed before a response was received")


def main() -> None:
    """Run the bundled tools over stdio."""

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
