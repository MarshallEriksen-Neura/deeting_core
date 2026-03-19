from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.services.plugin_market_service import PluginMarketService


@pytest.mark.asyncio
async def test_submit_repo_sends_submission_channel_and_user_id(monkeypatch):
    captured: dict[str, object] = {}

    def fake_send_task(name: str, args=None, kwargs=None, **_options):
        captured["name"] = name
        captured["args"] = args
        captured["kwargs"] = kwargs or {}
        return SimpleNamespace(id="task-123")

    monkeypatch.setattr(
        "app.services.plugin_market_service.celery_app.send_task",
        fake_send_task,
    )

    service = PluginMarketService(session=None)
    task_id = await service.submit_repo(
        user_id=uuid.UUID("00000000-0000-0000-0000-000000000123"),
        repo_url="https://github.com/acme/demo-skill.git",
        revision="main",
        skill_id="official.demo.skill",
        runtime_hint="opensandbox",
    )

    assert task_id == "task-123"
    assert captured["name"] == "skill_registry.ingest_repo"
    assert captured["args"] is None
    assert captured["kwargs"] == {
        "repo_url": "https://github.com/acme/demo-skill.git",
        "revision": "main",
        "skill_id": "official.demo.skill",
        "runtime_hint": "opensandbox",
        "source_subdir": None,
        "user_id": "00000000-0000-0000-0000-000000000123",
        "submission_channel": "plugin_market",
    }
