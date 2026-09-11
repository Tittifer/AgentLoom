"""Tests for bounded read-only bundled tools."""

import socket
from pathlib import Path
from typing import Any

import httpx
import pytest

from agentloom.tools.servers import builtin
from agentloom.tools.servers.builtin import (
    MAX_FETCH_BYTES,
    _normalize_text,  # pyright: ignore[reportPrivateUsage]
    _safe_workspace_files,  # pyright: ignore[reportPrivateUsage]
    _validate_public_url,  # pyright: ignore[reportPrivateUsage]
    get_current_time,
    web_fetch,
    workspace_glob,
    workspace_read,
    workspace_search,
)

REAL_ASYNC_CLIENT = httpx.AsyncClient


def test_workspace_tools_read_glob_and_search(tmp_path: Path) -> None:
    nested = tmp_path / "notes"
    nested.mkdir()
    (nested / "result.txt").write_text("Alpha\nAgentLoom result\nOmega", encoding="utf-8")

    listing = workspace_glob("**/*.txt", str(tmp_path))
    assert listing["files"] == ["notes/result.txt"]

    read = workspace_read("notes/result.txt", str(tmp_path), start_line=2, max_lines=1)
    assert read["content"] == "AgentLoom result"
    assert read["truncated"] is True

    search = workspace_search("agentloom", str(tmp_path), pattern="**/*.txt")
    assert search["matches"] == [
        {"path": "notes/result.txt", "line": 2, "text": "AgentLoom result"}
    ]


def test_workspace_read_rejects_path_escape(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="inside"):
        workspace_read("../secret.txt", str(tmp_path))


def test_workspace_tools_validate_input_and_file_boundaries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text_file = tmp_path / "result.txt"
    text_file.write_text("one\ntwo\nthree", encoding="utf-8")
    binary_file = tmp_path / "binary.txt"
    binary_file.write_bytes(b"\xff\xfe")

    with pytest.raises(ValueError, match="Pattern"):
        workspace_glob("", str(tmp_path))
    with pytest.raises(ValueError, match="inside"):
        _safe_workspace_files(str(tmp_path), "../*.txt")
    with pytest.raises(ValueError, match="at least"):
        workspace_read("result.txt", str(tmp_path), start_line=0)
    with pytest.raises(ValueError, match="does not exist"):
        workspace_read("missing.txt", str(tmp_path))
    with pytest.raises(ValueError, match="UTF-8"):
        workspace_read("binary.txt", str(tmp_path))
    with pytest.raises(ValueError, match="Query"):
        workspace_search("", str(tmp_path))
    binary_search = workspace_search("anything", str(tmp_path), pattern="binary.txt")
    assert binary_search["scanned_files"] == 0

    monkeypatch.setattr(builtin, "MAX_FILE_BYTES", 1)
    with pytest.raises(ValueError, match="exceeds"):
        workspace_read("result.txt", str(tmp_path))
    search = workspace_search("one", str(tmp_path), pattern="*.txt")
    assert search["scanned_files"] == 0


def test_workspace_search_case_and_result_limits(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("Alpha\nalpha", encoding="utf-8")
    result = workspace_search(
        "Alpha",
        str(tmp_path),
        pattern="*.txt",
        max_results=1,
        case_sensitive=True,
    )
    assert result["truncated"] is True
    assert result["matches"] == [{"path": "a.txt", "line": 1, "text": "Alpha"}]

    listing = workspace_glob("*.txt", str(tmp_path), max_results=1)
    assert listing["truncated"] is False
    assert _normalize_text(" one  two \n\n three ") == "one two\nthree"


def test_workspace_root_must_be_a_directory(tmp_path: Path) -> None:
    file_root = tmp_path / "file.txt"
    file_root.write_text("content", encoding="utf-8")
    with pytest.raises(ValueError, match="not a directory"):
        workspace_glob("*", str(file_root))
    with pytest.raises(ValueError, match="inside"):
        workspace_read(str(file_root), str(tmp_path))


async def test_web_url_policy_rejects_local_addresses() -> None:
    with pytest.raises(ValueError, match="private"):
        await _validate_public_url("http://127.0.0.1/secret")


async def test_web_url_policy_validates_syntax_and_dns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValueError, match="public HTTP"):
        await _validate_public_url("file:///tmp/secret")
    with pytest.raises(ValueError, match="credentials"):
        await _validate_public_url("https://user:password@example.com")
    with pytest.raises(ValueError, match="private"):
        await _validate_public_url("https://service.local/path")

    async def fail_dns(*args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        raise socket.gaierror("not found")

    monkeypatch.setattr(builtin.asyncio, "to_thread", fail_dns)
    with pytest.raises(ValueError, match="Could not resolve"):
        await _validate_public_url("https://missing.example")

    async def private_dns(*args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 443))]

    monkeypatch.setattr(builtin.asyncio, "to_thread", private_dns)
    with pytest.raises(ValueError, match="private"):
        await _validate_public_url("https://example.com")

    async def public_dns(*args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]

    monkeypatch.setattr(builtin.asyncio, "to_thread", public_dns)
    await _validate_public_url("https://example.com")


def _mock_http_client(
    monkeypatch: pytest.MonkeyPatch,
    handler: Any,
) -> None:
    transport = httpx.MockTransport(handler)

    def create_client(**kwargs: Any) -> httpx.AsyncClient:
        return REAL_ASYNC_CLIENT(transport=transport, **kwargs)

    monkeypatch.setattr(builtin.httpx, "AsyncClient", create_client)


async def test_web_fetch_extracts_html_and_follows_redirects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def allow_url(url: str) -> None:
        assert url.startswith("https://example.com")

    monkeypatch.setattr(builtin, "_validate_public_url", allow_url)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/start":
            return httpx.Response(302, headers={"location": "/page"})
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            text=(
                "<html><title> Example  page </title><body><h1>Hello</h1>"
                "<script>ignored()</script><p>AgentLoom</p></body></html>"
            ),
        )

    _mock_http_client(monkeypatch, handler)
    result = await web_fetch("https://example.com/start", max_chars=1_000)
    assert result["url"] == "https://example.com/page"
    assert result["title"] == "Example page"
    assert result["text"] == "Example page\nHello\nAgentLoom"
    assert result["truncated"] is False


async def test_web_fetch_bounds_content_and_rejects_unsafe_responses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def allow_url(url: str) -> None:
        del url

    monkeypatch.setattr(builtin, "_validate_public_url", allow_url)

    def large_handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            content=b"x" * (MAX_FETCH_BYTES + 1),
        )

    _mock_http_client(monkeypatch, large_handler)
    result = await web_fetch("https://example.com/data", max_chars=1_000)
    assert result["truncated"] is True
    assert len(str(result["text"])) == 1_000

    def binary_handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, headers={"content-type": "image/png"}, content=b"png")

    _mock_http_client(monkeypatch, binary_handler)
    with pytest.raises(ValueError, match="Unsupported"):
        await web_fetch("https://example.com/image")

    def redirect_handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(302)

    _mock_http_client(monkeypatch, redirect_handler)
    with pytest.raises(ValueError, match="redirect"):
        await web_fetch("https://example.com/redirect")


def test_current_time_supports_iana_timezone() -> None:
    result = get_current_time("Asia/Shanghai")
    assert result["timezone"] == "Asia/Shanghai"
    assert "+08:00" in result["iso8601"]

    with pytest.raises(ValueError, match="Unknown IANA"):
        get_current_time("Mars/Olympus")
