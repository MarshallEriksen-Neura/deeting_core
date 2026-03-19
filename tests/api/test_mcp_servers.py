from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from httpx import AsyncClient

from app.models.user_mcp_server import UserMcpServer


@pytest.mark.asyncio
async def test_create_stdio_server_draft(
    client: AsyncClient,
    auth_tokens: dict,
    AsyncSessionLocal,
    test_user: dict,
) -> None:
    payload = {
        "name": "Draft MCP",
        "description": "local draft import",
        "server_type": "stdio",
        "draft_config": {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem"],
            "env": {"TOKEN": "secret", "PATH": "/tmp"},
        },
    }

    resp = await client.post(
        "/api/v1/mcp/servers",
        json=payload,
        headers={"Authorization": f"Bearer {auth_tokens['access_token']}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["server_type"] == "stdio"
    assert data["is_enabled"] is False
    assert data["status"] == "draft"
    assert data["desired_enabled"] is False
    assert data["runtime_ready"] is False
    assert data["runtime_status_reason"] == "draft_config"
    assert data["availability_lane"] == "installable"
    assert data["install_required"] is True
    assert data.get("sse_url") in (None, "")

    async with AsyncSessionLocal() as session:
        server = await session.get(UserMcpServer, UUID(data["id"]))
        assert server is not None
        assert server.server_type == "stdio"
        assert server.is_enabled is False
        assert server.draft_config is not None
        assert server.draft_config.get("command") == "npx"
        assert server.draft_config.get("args") == [
            "-y",
            "@modelcontextprotocol/server-filesystem",
        ]
        assert server.draft_config.get("env_keys") == ["TOKEN", "PATH"]


@pytest.mark.asyncio
async def test_list_and_toggle_server_tools(
    client: AsyncClient,
    auth_tokens: dict,
    AsyncSessionLocal,
    monkeypatch,
    test_user: dict,
) -> None:
    async with AsyncSessionLocal() as session:
        user_id = UUID(test_user["id"])
        server = UserMcpServer(
            user_id=user_id,
            name="Remote MCP",
            description="remote",
            sse_url="https://example.com/mcp/sse",
            server_type="sse",
            auth_type="none",
            is_enabled=True,
            tools_cache=[
                {
                    "name": "search",
                    "description": "Search tool",
                    "input_schema": {"type": "object"},
                },
                {
                    "name": "browse",
                    "description": "Browse tool",
                    "input_schema": {"type": "object"},
                }
            ],
            disabled_tools=["browse"],
        )
        session.add(server)
        await session.commit()
        await session.refresh(server)

    from app.api.v1.endpoints import mcp as mcp_route

    monkeypatch.setattr(
        mcp_route.tool_sync_service,
        "list_user_indexed_tool_names_by_origin",
        AsyncMock(return_value={str(server.id): {"search"}}),
    )

    servers_resp = await client.get(
        "/api/v1/mcp/servers",
        headers={"Authorization": f"Bearer {auth_tokens['access_token']}"},
    )
    assert servers_resp.status_code == 200
    server_data = next(item for item in servers_resp.json() if item["id"] == str(server.id))
    assert server_data["desired_enabled"] is True
    assert server_data["runtime_ready"] is True
    assert server_data["index_status"] == "indexed"

    resp = await client.get(
        f"/api/v1/mcp/servers/{server.id}/tools",
        headers={"Authorization": f"Bearer {auth_tokens['access_token']}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data[0]["name"] == "search"
    assert data[0]["enabled"] is True
    assert data[0]["desired_enabled"] is True
    assert data[0]["runtime_ready"] is True
    assert data[0]["index_status"] == "indexed"
    assert data[1]["name"] == "browse"
    assert data[1]["enabled"] is False
    assert data[1]["desired_enabled"] is False
    assert data[1]["runtime_ready"] is False
    assert data[1]["runtime_status_reason"] == "tool_disabled"
    assert data[1]["index_status"] == "unknown"

    toggle_resp = await client.patch(
        f"/api/v1/mcp/servers/{server.id}/tools/browse",
        json={"enabled": True},
        headers={"Authorization": f"Bearer {auth_tokens['access_token']}"},
    )
    assert toggle_resp.status_code == 200
    toggled = toggle_resp.json()
    assert toggled["enabled"] is True
    assert toggled["desired_enabled"] is True
    assert toggled["runtime_ready"] is True
    assert toggled["runtime_status_reason"] is None
    assert toggled["index_status"] == "missing"

    refresh = await client.get(
        f"/api/v1/mcp/servers/{server.id}/tools",
        headers={"Authorization": f"Bearer {auth_tokens['access_token']}"},
    )
    assert refresh.status_code == 200
    refreshed = refresh.json()
    browse = next(item for item in refreshed if item["name"] == "browse")
    assert browse["enabled"] is True
    assert browse["desired_enabled"] is True
    assert browse["runtime_ready"] is True
    assert browse["runtime_status_reason"] is None
    assert browse["index_status"] == "missing"


@pytest.mark.asyncio
async def test_tool_test_endpoint(
    client: AsyncClient,
    auth_tokens: dict,
    AsyncSessionLocal,
    monkeypatch,
    test_user: dict,
) -> None:
    async with AsyncSessionLocal() as session:
        user_id = UUID(test_user["id"])
        server = UserMcpServer(
            user_id=user_id,
            name="Remote MCP",
            description="remote",
            sse_url="https://example.com/mcp/sse",
            server_type="sse",
            auth_type="none",
            is_enabled=True,
            tools_cache=[
                {
                    "name": "echo",
                    "description": "Echo tool",
                    "input_schema": {"type": "object"},
                }
            ],
            disabled_tools=[],
        )
        session.add(server)
        await session.commit()
        await session.refresh(server)

    from app.api.v1.endpoints import mcp as mcp_route

    monkeypatch.setattr(
        mcp_route.mcp_client,
        "call_tool",
        AsyncMock(return_value={"ok": True}),
    )

    resp = await client.post(
        "/api/v1/mcp/tools/test",
        json={
            "server_id": str(server.id),
            "tool_name": "echo",
            "arguments": {"text": "hi"},
        },
        headers={"Authorization": f"Bearer {auth_tokens['access_token']}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["result"] == {"ok": True}
    assert data["trace_id"]
    assert data["logs"]


@pytest.mark.asyncio
async def test_server_recommended_action_semantics(
    client: AsyncClient,
    auth_tokens: dict,
    AsyncSessionLocal,
    monkeypatch,
    test_user: dict,
) -> None:
    async with AsyncSessionLocal() as session:
        user_id = UUID(test_user["id"])
        disabled_server = UserMcpServer(
            user_id=user_id,
            name="Disabled Remote",
            description="disabled",
            sse_url="https://example.com/disabled/sse",
            server_type="sse",
            auth_type="none",
            is_enabled=False,
            tools_cache=[{"name": "search", "description": "Search", "input_schema": {}}],
            disabled_tools=[],
        )
        unsynced_server = UserMcpServer(
            user_id=user_id,
            name="Unsynced Remote",
            description="needs sync",
            sse_url="https://example.com/unsynced/sse",
            server_type="sse",
            auth_type="none",
            is_enabled=True,
            tools_cache=[],
            disabled_tools=[],
        )
        indexed_gap_server = UserMcpServer(
            user_id=user_id,
            name="Indexed Gap Remote",
            description="missing index",
            sse_url="https://example.com/index-gap/sse",
            server_type="sse",
            auth_type="none",
            is_enabled=True,
            tools_cache=[{"name": "browse", "description": "Browse", "input_schema": {}}],
            disabled_tools=[],
        )
        session.add_all([disabled_server, unsynced_server, indexed_gap_server])
        await session.commit()
        await session.refresh(disabled_server)
        await session.refresh(unsynced_server)
        await session.refresh(indexed_gap_server)

    from app.api.v1.endpoints import mcp as mcp_route

    monkeypatch.setattr(
        mcp_route.tool_sync_service,
        "list_user_indexed_tool_names_by_origin",
        AsyncMock(return_value={str(indexed_gap_server.id): set()}),
    )

    resp = await client.get(
        "/api/v1/mcp/servers",
        headers={"Authorization": f"Bearer {auth_tokens['access_token']}"},
    )
    assert resp.status_code == 200
    payload = {item["id"]: item for item in resp.json()}

    disabled = payload[str(disabled_server.id)]
    assert disabled["runtime_ready"] is False
    assert disabled["runtime_status_reason"] == "disabled"
    assert disabled["recommended_action"] == "enable_server"

    unsynced = payload[str(unsynced_server.id)]
    assert unsynced["runtime_ready"] is False
    assert unsynced["runtime_status_reason"] == "no_cached_tools"
    assert unsynced["recommended_action"] == "sync_server"

    indexed_gap = payload[str(indexed_gap_server.id)]
    assert indexed_gap["runtime_ready"] is True
    assert indexed_gap["index_status"] == "missing"
    assert indexed_gap["recommended_action"] == "sync_server"
