from __future__ import annotations

from types import SimpleNamespace
import uuid

import pytest
from fastapi import HTTPException

from app.services.plugin_ui_gateway_service import PluginUiGatewayService


class _FakeSkillRepo:
    def __init__(self, skill):
        self.skill = skill

    async def get_by_id(self, _skill_id: str):
        return self.skill


@pytest.mark.asyncio
async def test_issue_renderer_session_is_disabled_for_cloud_plugin_ui() -> None:
    skill = SimpleNamespace(
        id="com.example.stock",
        status="active",
        source_repo="https://github.com/acme/stock.git",
        source_revision="main",
        manifest_json={"ui_bundle": {"renderer_asset_path": "index.html"}},
    )
    service = PluginUiGatewayService(skill_repo=_FakeSkillRepo(skill))

    with pytest.raises(HTTPException, match="desktop app"):
        await service.issue_renderer_session(
            user_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
            skill_id="com.example.stock",
            base_url="https://deeting.example.com",
            ttl_seconds=300,
        )
