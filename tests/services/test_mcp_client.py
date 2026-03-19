from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx
import pytest

from app.services.mcp.client import MCPClient


def _install_fake_sdk(monkeypatch, tools):
    @asynccontextmanager
    async def fake_sse_client(*_args, **_kwargs):
        yield object(), object()

    class FakeSession:
        def __init__(self, _read, _write):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def initialize(self):
            return None

        async def list_tools(self):
            items = [
                SimpleNamespace(
                    name=tool["name"],
                    description=tool.get("description"),
                    inputSchema=tool.get("inputSchema"),
                )
                for tool in tools
            ]
            return SimpleNamespace(tools=items)

    monkeypatch.setattr("app.services.mcp.client.sse_client", fake_sse_client)
    monkeypatch.setattr("app.services.mcp.client.ClientSession", FakeSession)


@pytest.mark.asyncio
async def test_fetch_tools_returns_direct_post_tools(monkeypatch):
    _install_fake_sdk(
        monkeypatch,
        [
            {
                "name": "search",
                "description": "desc",
                "inputSchema": {"type": "object"},
            },
        ],
    )

    client = MCPClient(timeout=1, max_retries=1)
    tools = await client.fetch_tools("https://example.com/sse")

    assert len(tools) == 1
    assert tools[0].name == "search"


@pytest.mark.asyncio
async def test_fetch_tools_returns_sse_tools(monkeypatch):
    _install_fake_sdk(
        monkeypatch,
        [
            {
                "name": "sse-tool",
                "description": "desc",
                "inputSchema": {"type": "object"},
            },
        ],
    )

    client = MCPClient(timeout=1, max_retries=1)
    tools = await client.fetch_tools("https://example.com/sse")

    assert len(tools) == 1
    assert tools[0].name == "sse-tool"


def _install_fake_streamable_sdk(monkeypatch, tools):
    @asynccontextmanager
    async def fake_streamable_http_client(*_args, **_kwargs):
        yield object(), object(), lambda: "session-id"

    class FakeSession:
        def __init__(self, _read, _write):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def initialize(self):
            return None

        async def list_tools(self):
            items = [
                SimpleNamespace(
                    name=tool["name"],
                    description=tool.get("description"),
                    inputSchema=tool.get("inputSchema"),
                )
                for tool in tools
            ]
            return SimpleNamespace(tools=items)

        async def call_tool(self, name, arguments):
            return SimpleNamespace(content=[{"type": "text", "text": "result"}])

    monkeypatch.setattr(
        "app.services.mcp.client.streamable_http_client", fake_streamable_http_client
    )
    monkeypatch.setattr("app.services.mcp.client.ClientSession", FakeSession)


@pytest.mark.asyncio
async def test_fetch_tools_streamable_http_direct(monkeypatch):
    _install_fake_streamable_sdk(
        monkeypatch,
        [
            {
                "name": "streamable-tool",
                "description": "desc",
                "inputSchema": {"type": "object"},
            },
        ],
    )

    client = MCPClient(timeout=1, max_retries=1)
    tools = await client.fetch_tools(
        "https://example.com/mcp",
        transport_type="streamable-http",
    )

    assert len(tools) == 1
    assert tools[0].name == "streamable-tool"


@pytest.mark.asyncio
async def test_fetch_tools_sse_405_fallback_to_streamable_http(monkeypatch):
    @asynccontextmanager
    async def fake_sse_client(*_args, **_kwargs):
        response = httpx.Response(
            405,
            request=httpx.Request("GET", "https://example.com/sse"),
        )
        error = httpx.HTTPStatusError(
            "Method Not Allowed",
            request=response.request,
            response=response,
        )
        raise error
        yield  # pragma: no cover

    monkeypatch.setattr("app.services.mcp.client.sse_client", fake_sse_client)
    _install_fake_streamable_sdk(
        monkeypatch,
        [
            {
                "name": "fallback-tool",
                "description": "desc",
                "inputSchema": {"type": "object"},
            },
        ],
    )

    client = MCPClient(timeout=1, max_retries=1)
    tools = await client.fetch_tools("https://example.com/sse")

    assert len(tools) == 1
    assert tools[0].name == "fallback-tool"


@pytest.mark.asyncio
async def test_call_tool_streamable_http_direct(monkeypatch):
    _install_fake_streamable_sdk(monkeypatch, [])

    client = MCPClient(timeout=1, max_retries=1)
    result = await client.call_tool(
        "https://example.com/mcp",
        "search",
        {"query": "hello"},
        transport_type="streamable-http",
    )

    assert result == [{"type": "text", "text": "result"}]


@pytest.mark.asyncio
async def test_call_tool_sse_405_fallback_to_streamable_http(monkeypatch):
    @asynccontextmanager
    async def fake_sse_client(*_args, **_kwargs):
        response = httpx.Response(
            405,
            request=httpx.Request("GET", "https://example.com/sse"),
        )
        error = httpx.HTTPStatusError(
            "Method Not Allowed",
            request=response.request,
            response=response,
        )
        raise error
        yield  # pragma: no cover

    monkeypatch.setattr("app.services.mcp.client.sse_client", fake_sse_client)
    _install_fake_streamable_sdk(monkeypatch, [])

    client = MCPClient(timeout=1, max_retries=1)
    result = await client.call_tool(
        "https://example.com/sse",
        "search",
        {"query": "hello"},
    )

    assert result == [{"type": "text", "text": "result"}]
