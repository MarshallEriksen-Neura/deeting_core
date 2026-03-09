from __future__ import annotations

import json
from uuid import uuid4

import httpx
import pytest

from app.services.memory.qdrant_collection_migration_service import (
    QdrantCollectionMigrationService,
)


def _patch_new_names(monkeypatch):
    monkeypatch.setattr("app.storage.qdrant_kb_collections.settings.QDRANT_KB_SYSTEM_COLLECTION", "system_memory")
    monkeypatch.setattr("app.storage.qdrant_kb_collections.settings.QDRANT_KB_CANDIDATES_COLLECTION", "infra_candidates")
    monkeypatch.setattr("app.storage.qdrant_kb_collections.settings.QDRANT_KB_USER_COLLECTION", "user_memory")
    monkeypatch.setattr("app.storage.qdrant_kb_collections.settings.QDRANT_TOOL_SYSTEM_COLLECTION", "system_capability_tools")
    monkeypatch.setattr("app.storage.qdrant_kb_collections.settings.QDRANT_TOOL_USER_COLLECTION_PREFIX", "user_capability")
    monkeypatch.setattr("app.storage.qdrant_kb_collections.settings.QDRANT_SKILL_COLLECTION", "system_capability_skills")
    monkeypatch.setattr("app.storage.qdrant_kb_collections.settings.QDRANT_ASSISTANT_COLLECTION", "system_capability_assistants")
    monkeypatch.setattr("app.storage.qdrant_kb_collections.settings.QDRANT_MARKETPLACE_COLLECTION", "system_capability_marketplace")
    monkeypatch.setattr("app.storage.qdrant_kb_collections.settings.QDRANT_SEMANTIC_CACHE_COLLECTION", "infra_semantic_cache")
    monkeypatch.setattr("app.services.memory.qdrant_collection_migration_service.settings.QDRANT_KB_USER_COLLECTION_STRATEGY", "per_user")


@pytest.mark.asyncio
async def test_build_legacy_backfill_plan_maps_system_and_user_collections(monkeypatch):
    _patch_new_names(monkeypatch)
    user_id = uuid4()
    service = QdrantCollectionMigrationService()

    plan = await service.build_legacy_backfill_plan(
        existing_collections=[
            "kb_system",
            "skill_registry",
            f"kb_user_{user_id.hex}",
            f"kb_user_{user_id.hex}_tools",
        ]
    )

    pairs = {(item.source, item.target) for item in plan}
    assert ("kb_system", "system_memory") in pairs
    assert ("skill_registry", "system_capability_skills") in pairs
    assert (f"kb_user_{user_id.hex}", f"user_memory_{user_id.hex}") in pairs
    assert (f"kb_user_{user_id.hex}_tools", f"user_capability_{user_id.hex}_tools") in pairs


@pytest.mark.asyncio
async def test_backfill_collection_copies_legacy_points(monkeypatch):
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        path = request.url.path
        if path == "/collections/kb_system" and request.method == "GET":
            return httpx.Response(200, json={"result": {"config": {"params": {"vectors": {"text": {"size": 2}}}}}})
        if path == "/collections/system_memory" and request.method == "GET":
            return httpx.Response(404, json={})
        if path == "/collections/system_memory" and request.method == "PUT":
            return httpx.Response(200, json={"result": {"status": "ok"}})
        if path == "/collections/kb_system/points/scroll" and request.method == "POST":
            body = json.loads(request.content.decode())
            assert body["with_vector"] is True
            return httpx.Response(
                200,
                json={
                    "result": {
                        "points": [
                            {
                                "id": "p1",
                                "vector": {"text": [0.1, 0.2]},
                                "payload": {"scope": "system"},
                            }
                        ],
                        "next_page_offset": None,
                    }
                },
            )
        if path == "/collections/system_memory/points" and request.method == "PUT":
            body = json.loads(request.content.decode())
            assert body["points"][0]["id"] == "p1"
            assert body["points"][0]["vector"]["text"] == [0.1, 0.2]
            return httpx.Response(200, json={"result": {"status": "ok"}})
        return httpx.Response(404, json={})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://qdrant.test")
    monkeypatch.setattr(
        "app.services.memory.qdrant_collection_migration_service.get_qdrant_client",
        lambda: client,
    )
    service = QdrantCollectionMigrationService()

    copied = await service.backfill_collection(source="kb_system", target="system_memory")
    await client.aclose()

    assert copied == 1
    assert any(req.url.path == "/collections/system_memory/points" for req in requests)