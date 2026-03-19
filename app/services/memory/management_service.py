from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.memory_snapshot_repository import MemorySnapshotRepository
from app.schemas.memory import (
    MemoryItem,
    MemoryListResponse,
    MemoryRollbackRequest,
    MemoryRollbackResponse,
    MemorySnapshotItem,
    MemorySnapshotListResponse,
    MemoryUpdateRequest,
)
from app.services.memory.external_memory import search_user_memories
from app.services.vector.qdrant_user_service import QdrantUserVectorService

_SYSTEM_PAYLOAD_KEYS = {"content", "user_id", "plugin_id", "embedding_model"}
_GOVERNANCE_KEYS = {"recall_when", "memory_tier", "is_core", "is_boot"}


def _user_metadata(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    metadata = {key: value for key, value in payload.items() if key not in _SYSTEM_PAYLOAD_KEYS}
    return metadata or None


def _read_string(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None


def _read_bool(payload: dict[str, Any], key: str) -> bool | None:
    value = payload.get(key)
    return value if isinstance(value, bool) else None


def _merge_metadata(
    current: dict[str, Any] | None, request: MemoryUpdateRequest
) -> dict[str, Any] | None:
    next_metadata = dict(current or {})
    provided_fields = getattr(request, "model_fields_set", set())

    if "recall_when" in provided_fields:
        recall_when = (request.recall_when or "").strip()
        if recall_when:
            next_metadata["recall_when"] = recall_when
        else:
            next_metadata.pop("recall_when", None)

    if "memory_tier" in provided_fields:
        memory_tier = (request.memory_tier or "").strip()
        if memory_tier:
            next_metadata["memory_tier"] = memory_tier
        else:
            next_metadata.pop("memory_tier", None)

    if "is_core" in provided_fields:
        if request.is_core is None:
            next_metadata.pop("is_core", None)
        else:
            next_metadata["is_core"] = request.is_core

    if "is_boot" in provided_fields:
        if request.is_boot is None:
            next_metadata.pop("is_boot", None)
        else:
            next_metadata["is_boot"] = request.is_boot

    return next_metadata or None


class MemoryManagementService:
    def __init__(
        self,
        *,
        user_id: uuid.UUID,
        vector_service: QdrantUserVectorService,
        snapshot_repository: MemorySnapshotRepository,
        session: AsyncSession,
    ) -> None:
        self.user_id = user_id
        self.vector_service = vector_service
        self.snapshot_repository = snapshot_repository
        self.session = session

    @staticmethod
    def _to_memory_item(item: dict[str, Any], *, score_key: str = "score") -> MemoryItem:
        payload = item.get("payload") or {}
        return MemoryItem(
            id=str(item.get("id") or ""),
            content=str(item.get("content") or ""),
            payload=payload,
            score=item.get(score_key),
            recall_when=_read_string(payload, "recall_when"),
            memory_tier=_read_string(payload, "memory_tier"),
            is_core=_read_bool(payload, "is_core"),
            is_boot=_read_bool(payload, "is_boot"),
        )

    async def list_memories(self, *, limit: int, cursor: str | None) -> MemoryListResponse:
        items, next_cursor = await self.vector_service.list_points(limit=limit, cursor=cursor)
        return MemoryListResponse(
            items=[self._to_memory_item(item) for item in items],
            next_cursor=next_cursor,
        )

    async def search_memories(self, *, query: str, limit: int) -> list[MemoryItem]:
        results = await search_user_memories(user_id=self.user_id, query=query, limit=limit)
        return [self._to_memory_item(item, score_key="final_score") for item in results]

    async def update_memory(self, *, memory_id: str, request: MemoryUpdateRequest) -> MemoryItem:
        current = await self.vector_service.get_point(memory_id)
        current_payload = dict((current or {}).get("payload") or {})
        preserved_metadata = _user_metadata(current_payload)
        next_metadata = _merge_metadata(preserved_metadata, request)
        await self.snapshot_repository.create(
            user_id=self.user_id,
            memory_point_id=memory_id,
            action="update",
            old_content=(current or {}).get("content"),
            new_content=request.content,
            old_metadata=preserved_metadata,
            new_metadata=next_metadata,
        )
        await self.vector_service.upsert(
            content=request.content,
            payload=next_metadata,
            id=memory_id,
        )
        await self.session.commit()
        current_payload["content"] = request.content
        for key in _GOVERNANCE_KEYS:
            if next_metadata and key in next_metadata:
                current_payload[key] = next_metadata[key]
            else:
                current_payload.pop(key, None)
        return self._to_memory_item(
            {"id": memory_id, "content": request.content, "payload": current_payload}
        )

    async def delete_memory(self, *, memory_id: str) -> None:
        current = await self.vector_service.get_point(memory_id)
        current_payload = dict((current or {}).get("payload") or {})
        await self.snapshot_repository.create(
            user_id=self.user_id,
            memory_point_id=memory_id,
            action="delete",
            old_content=(current or {}).get("content"),
            old_metadata=_user_metadata(current_payload),
        )
        await self.vector_service.delete(ids=[memory_id])
        await self.session.commit()

    async def clear_memories(self) -> None:
        await self.vector_service.clear_all()

    async def list_snapshots(self, *, memory_id: str, limit: int) -> MemorySnapshotListResponse:
        snapshots = await self.snapshot_repository.list_by_memory(
            user_id=self.user_id,
            memory_point_id=memory_id,
            limit=limit,
        )
        return MemorySnapshotListResponse(
            items=[MemorySnapshotItem.model_validate(snapshot) for snapshot in snapshots]
        )

    async def rollback_memory(
        self, *, memory_id: str, request: MemoryRollbackRequest
    ) -> MemoryRollbackResponse:
        snapshot = await self.snapshot_repository.get_by_id(
            snapshot_id=request.snapshot_id,
            user_id=self.user_id,
        )
        if not snapshot:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Snapshot {request.snapshot_id} not found.",
            )
        if snapshot.memory_point_id != memory_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Snapshot does not belong to this memory.",
            )
        if not snapshot.old_content:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Snapshot has no old_content to restore.",
            )

        current = await self.vector_service.get_point(memory_id)
        current_payload = dict((current or {}).get("payload") or {})
        current_metadata = _user_metadata(current_payload)
        restore_metadata = snapshot.old_metadata or current_metadata
        await self.snapshot_repository.create(
            user_id=self.user_id,
            memory_point_id=memory_id,
            action="rollback",
            old_content=(current or {}).get("content"),
            new_content=snapshot.old_content,
            old_metadata=current_metadata,
            new_metadata=restore_metadata,
        )
        await self.vector_service.upsert(
            content=snapshot.old_content,
            payload=restore_metadata,
            id=memory_id,
        )
        await self.session.commit()
        return MemoryRollbackResponse(
            success=True,
            memory_point_id=memory_id,
            restored_content=snapshot.old_content,
        )


__all__ = ["MemoryManagementService"]