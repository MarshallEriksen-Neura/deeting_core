from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.models.skill_registry import SkillRegistry


@pytest.mark.asyncio
async def test_plugin_market_installs_endpoint_returns_empty_after_cloud_install_removal(
    client: AsyncClient,
    auth_tokens: dict,
    AsyncSessionLocal,
) -> None:
    async with AsyncSessionLocal() as session:
        skill = SkillRegistry(
            id="plugin.market.disabled",
            name="Disabled Install Plugin",
            status="active",
            source_repo="https://github.com/example/disabled-install",
            source_revision="main",
        )
        session.add(skill)
        await session.commit()

    response = await client.get(
        "/api/v1/plugin-market/installs",
        headers={"Authorization": f"Bearer {auth_tokens['access_token']}"},
    )

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_plugin_market_install_endpoint_is_gone(
    client: AsyncClient,
    auth_tokens: dict,
) -> None:
    response = await client.post(
        "/api/v1/plugin-market/plugins/plugin.any/install",
        headers={"Authorization": f"Bearer {auth_tokens['access_token']}"},
        json={},
    )

    assert response.status_code == 410
    assert "desktop app" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_plugin_market_uninstall_endpoint_is_gone(
    client: AsyncClient,
    auth_tokens: dict,
) -> None:
    response = await client.delete(
        "/api/v1/plugin-market/plugins/plugin.any/install",
        headers={"Authorization": f"Bearer {auth_tokens['access_token']}"},
    )

    assert response.status_code == 410
    assert "desktop app" in response.json()["detail"].lower()
