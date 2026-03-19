from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.schemas.memory import MemoryRollbackRequest, MemoryUpdateRequest
from app.services.memory.management_service import MemoryManagementService


class FakeSession:
    def __init__(self) -> None:
        self.commit_calls = 0

    async def commit(self) -> None:
        self.commit_calls += 1


class FakeSnapshotRepository:
    def __init__(self, snapshot: SimpleNamespace | None = None) -> None:
        self.created: list[dict] = []
        self.snapshot = snapshot

    async def create(self, **kwargs):
        self.created.append(kwargs)
        return SimpleNamespace(**kwargs)

    async def list_by_memory(self, **kwargs):  # pragma: no cover - not used here
        return []

    async def get_by_id(self, **kwargs):
        return self.snapshot


class FakeVectorService:
    def __init__(self, current_point: dict | None) -> None:
        self.current_point = current_point
        self.get_point_calls: list[str] = []
        self.upsert_calls: list[dict] = []

    async def get_point(self, point_id: str):
        self.get_point_calls.append(point_id)
        return self.current_point

    async def upsert(self, *, content: str, payload: dict | None = None, id: str | None = None):
        self.upsert_calls.append({"content": content, "payload": payload, "id": id})
        return id or "generated-id"


@pytest.mark.asyncio
async def test_update_memory_uses_exact_point_lookup_and_preserves_metadata():
    user_id = uuid.uuid4()
    session = FakeSession()
    vector_service = FakeVectorService(
        {
            "id": "memory-1",
            "content": "before",
            "payload": {
                "content": "before",
                "category": "fact",
                "tags": ["profile"],
                "user_id": str(user_id),
                "embedding_model": "text-embed",
            },
        }
    )
    snapshot_repo = FakeSnapshotRepository()
    service = MemoryManagementService(
        user_id=user_id,
        vector_service=vector_service,  # type: ignore[arg-type]
        snapshot_repository=snapshot_repo,  # type: ignore[arg-type]
        session=session,  # type: ignore[arg-type]
    )

    result = await service.update_memory(
        memory_id="memory-1",
        request=MemoryUpdateRequest(content="after"),
    )

    assert vector_service.get_point_calls == ["memory-1"]
    assert snapshot_repo.created == [
        {
            "user_id": user_id,
            "memory_point_id": "memory-1",
            "action": "update",
            "old_content": "before",
            "new_content": "after",
            "old_metadata": {"category": "fact", "tags": ["profile"]},
            "new_metadata": {"category": "fact", "tags": ["profile"]},
        }
    ]
    assert vector_service.upsert_calls == [
        {
            "content": "after",
            "payload": {"category": "fact", "tags": ["profile"]},
            "id": "memory-1",
        }
    ]
    assert session.commit_calls == 1
    assert result.content == "after"
    assert result.payload["content"] == "after"


@pytest.mark.asyncio
async def test_update_memory_merges_governance_metadata_fields():
    user_id = uuid.uuid4()
    session = FakeSession()
    vector_service = FakeVectorService(
        {
            "id": "memory-3",
            "content": "before",
            "payload": {
                "content": "before",
                "category": "preference",
                "tags": ["style"],
                "recall_when": "when user asks about tone",
                "user_id": str(user_id),
            },
        }
    )
    snapshot_repo = FakeSnapshotRepository()
    service = MemoryManagementService(
        user_id=user_id,
        vector_service=vector_service,  # type: ignore[arg-type]
        snapshot_repository=snapshot_repo,  # type: ignore[arg-type]
        session=session,  # type: ignore[arg-type]
    )

    result = await service.update_memory(
        memory_id="memory-3",
        request=MemoryUpdateRequest(
            content="after",
            recall_when="when user asks about response style",
            memory_tier="core",
            is_core=True,
            is_boot=True,
        ),
    )

    assert snapshot_repo.created[0]["old_metadata"] == {
        "category": "preference",
        "tags": ["style"],
        "recall_when": "when user asks about tone",
    }
    assert snapshot_repo.created[0]["new_metadata"] == {
        "category": "preference",
        "tags": ["style"],
        "recall_when": "when user asks about response style",
        "memory_tier": "core",
        "is_core": True,
        "is_boot": True,
    }
    assert vector_service.upsert_calls[0]["payload"] == {
        "category": "preference",
        "tags": ["style"],
        "recall_when": "when user asks about response style",
        "memory_tier": "core",
        "is_core": True,
        "is_boot": True,
    }
    assert result.payload["memory_tier"] == "core"
    assert result.payload["is_boot"] is True


@pytest.mark.asyncio
async def test_rollback_memory_restores_snapshot_content_and_metadata():
    user_id = uuid.uuid4()
    snapshot_id = uuid.uuid4()
    session = FakeSession()
    vector_service = FakeVectorService(
        {
            "id": "memory-2",
            "content": "current",
            "payload": {
                "content": "current",
                "category": "fact",
                "tags": ["new"],
                "user_id": str(user_id),
            },
        }
    )
    snapshot_repo = FakeSnapshotRepository(
        SimpleNamespace(
            id=snapshot_id,
            user_id=user_id,
            memory_point_id="memory-2",
            action="update",
            old_content="restored",
            new_content="current",
            old_metadata={"category": "fact", "tags": ["old"]},
            new_metadata={"category": "fact", "tags": ["new"]},
        )
    )
    service = MemoryManagementService(
        user_id=user_id,
        vector_service=vector_service,  # type: ignore[arg-type]
        snapshot_repository=snapshot_repo,  # type: ignore[arg-type]
        session=session,  # type: ignore[arg-type]
    )

    result = await service.rollback_memory(
        memory_id="memory-2",
        request=MemoryRollbackRequest(snapshot_id=snapshot_id),
    )

    assert snapshot_repo.created == [
        {
            "user_id": user_id,
            "memory_point_id": "memory-2",
            "action": "rollback",
            "old_content": "current",
            "new_content": "restored",
            "old_metadata": {"category": "fact", "tags": ["new"]},
            "new_metadata": {"category": "fact", "tags": ["old"]},
        }
    ]
    assert vector_service.upsert_calls == [
        {
            "content": "restored",
            "payload": {"category": "fact", "tags": ["old"]},
            "id": "memory-2",
        }
    ]
    assert session.commit_calls == 1
    assert result.success is True
    assert result.restored_content == "restored"