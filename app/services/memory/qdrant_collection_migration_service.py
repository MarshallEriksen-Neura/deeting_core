from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import UUID

from app.core.config import settings
from app.qdrant_client import get_qdrant_client
from app.storage.qdrant_kb_collections import (
    get_assistant_collection_name,
    get_infra_candidates_collection_name,
    get_marketplace_collection_name,
    get_semantic_cache_collection_name,
    get_skill_collection_name,
    get_system_capability_tool_collection_name,
    get_system_memory_collection_name,
    get_user_capability_tool_collection_name,
    get_user_memory_collection_name,
)
from app.storage.qdrant_kb_store import (
    QDRANT_DEFAULT_VECTOR_NAME,
    ensure_collection_vector_size,
    get_collection_vector_size,
    scroll_points,
    upsert_points,
)

_LEGACY_USER_MEMORY_RE = re.compile(r"^kb_user_([0-9a-f]{32})$")
_LEGACY_USER_TOOL_RE = re.compile(r"^kb_user_([0-9a-f]{32})_tools$")


@dataclass(frozen=True)
class CollectionMigrationPlanItem:
    source: str
    target: str
    category: str


class QdrantCollectionMigrationService:
    def __init__(self):
        self.client = get_qdrant_client()

    async def list_existing_collections(self) -> list[str]:
        resp = await self.client.get("/collections")
        resp.raise_for_status()
        rows = resp.json().get("result", {}).get("collections", [])
        names = [str(item.get("name") or "").strip() for item in rows if isinstance(item, dict)]
        return [name for name in names if name]

    async def build_legacy_backfill_plan(
        self,
        *,
        include_user: bool = True,
        existing_collections: list[str] | None = None,
    ) -> list[CollectionMigrationPlanItem]:
        names = existing_collections or await self.list_existing_collections()
        plan: list[CollectionMigrationPlanItem] = []
        for source, target, category in self._system_legacy_pairs():
            if source in names and source != target:
                plan.append(CollectionMigrationPlanItem(source, target, category))
        if include_user:
            for name in names:
                item = self._map_legacy_user_collection(name)
                if item and item.source != item.target:
                    plan.append(item)
        plan.sort(key=lambda item: (item.category, item.source, item.target))
        return plan

    async def backfill_legacy_collections(
        self,
        *,
        include_user: bool = True,
        batch_size: int = 100,
    ) -> dict[str, int]:
        plan = await self.build_legacy_backfill_plan(include_user=include_user)
        copied_points = 0
        copied_collections = 0
        for item in plan:
            copied = await self.backfill_collection(
                source=item.source,
                target=item.target,
                batch_size=batch_size,
            )
            copied_points += copied
            if copied > 0:
                copied_collections += 1
        return {
            "planned_collections": len(plan),
            "copied_collections": copied_collections,
            "copied_points": copied_points,
        }

    async def backfill_collection(
        self,
        *,
        source: str,
        target: str,
        batch_size: int = 100,
    ) -> int:
        vector_size = await get_collection_vector_size(self.client, collection_name=source)
        if vector_size is None:
            return 0
        await ensure_collection_vector_size(
            self.client,
            collection_name=target,
            vector_size=vector_size,
        )
        copied = 0
        offset = None
        while True:
            points, offset = await scroll_points(
                self.client,
                collection_name=source,
                limit=batch_size,
                with_payload=True,
                with_vector=True,
                offset=offset,
            )
            batch = [point for point in (self._normalize_point(item) for item in points) if point]
            if batch:
                await upsert_points(self.client, collection_name=target, points=batch, wait=True)
                copied += len(batch)
            if not points or offset is None:
                break
        return copied

    @staticmethod
    def _system_legacy_pairs() -> list[tuple[str, str, str]]:
        return [
            ("kb_system", get_system_memory_collection_name(), "system_memory"),
            ("kb_candidates", get_infra_candidates_collection_name(), "infra_candidates"),
            ("sys_tool_index", get_system_capability_tool_collection_name(), "system_capability"),
            ("skill_registry", get_skill_collection_name(), "system_capability"),
            ("expert_network", get_assistant_collection_name(), "system_capability"),
            ("plugin_marketplace", get_marketplace_collection_name(), "system_capability"),
            ("semantic_cache", get_semantic_cache_collection_name(), "infra_cache"),
        ]

    @staticmethod
    def _normalize_point(point: dict) -> dict | None:
        point_id = str(point.get("id") or "").strip()
        payload = point.get("payload") if isinstance(point.get("payload"), dict) else {}
        vector = QdrantCollectionMigrationService._extract_vector(point.get("vector"))
        if not point_id or not vector:
            return None
        return {"id": point_id, "vector": vector, "payload": payload}

    @staticmethod
    def _extract_vector(raw_vector) -> list[float] | None:
        if isinstance(raw_vector, list) and raw_vector:
            return raw_vector
        if isinstance(raw_vector, dict):
            direct = raw_vector.get(QDRANT_DEFAULT_VECTOR_NAME)
            if isinstance(direct, list) and direct:
                return direct
            if len(raw_vector) == 1:
                only = next(iter(raw_vector.values()))
                if isinstance(only, list) and only:
                    return only
        return None

    @staticmethod
    def _map_legacy_user_collection(name: str) -> CollectionMigrationPlanItem | None:
        tool_match = _LEGACY_USER_TOOL_RE.match(name)
        if tool_match:
            user_id = UUID(hex=tool_match.group(1))
            return CollectionMigrationPlanItem(
                source=name,
                target=get_user_capability_tool_collection_name(user_id),
                category="user_capability",
            )

        memory_match = _LEGACY_USER_MEMORY_RE.match(name)
        if not memory_match:
            return None

        strategy = str(
            getattr(settings, "QDRANT_KB_USER_COLLECTION_STRATEGY", "per_user") or "per_user"
        ).strip().lower()
        if strategy == "sharded_by_model":
            return None
        user_id = UUID(hex=memory_match.group(1))
        return CollectionMigrationPlanItem(
            source=name,
            target=get_user_memory_collection_name(user_id),
            category="user_memory",
        )


__all__ = ["CollectionMigrationPlanItem", "QdrantCollectionMigrationService"]