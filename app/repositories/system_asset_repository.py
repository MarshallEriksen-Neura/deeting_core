from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.system_asset import SystemAsset
from app.repositories.base import BaseRepository


class SystemAssetRepository(BaseRepository[SystemAsset]):
    model = SystemAsset

    def __init__(self, session: AsyncSession):
        super().__init__(session, SystemAsset)

    async def get_by_asset_id(self, asset_id: str) -> SystemAsset | None:
        result = await self.session.execute(
            select(SystemAsset).where(SystemAsset.asset_id == asset_id)
        )
        return result.scalars().first()

    async def upsert_asset(self, *, asset_id: str, obj_in: dict) -> SystemAsset:
        existing = await self.get_by_asset_id(asset_id)
        if existing:
            for field, value in obj_in.items():
                setattr(existing, field, value)
            self.session.add(existing)
            await self.session.flush()
            await self.session.refresh(existing)
            return existing

        created = SystemAsset(asset_id=asset_id, **obj_in)
        self.session.add(created)
        await self.session.flush()
        await self.session.refresh(created)
        return created

    async def list_system_assets(
        self,
        *,
        asset_kind: str | None = None,
        status: str = "active",
        limit: int = 100,
    ) -> list[SystemAsset]:
        stmt: Select[tuple[SystemAsset]] = select(SystemAsset).where(
            SystemAsset.owner_scope == "system",
            SystemAsset.status == status,
        )
        if asset_kind:
            stmt = stmt.where(SystemAsset.asset_kind == asset_kind)
        stmt = stmt.order_by(SystemAsset.asset_id.asc()).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def archive_registry_entity_assets_except(
        self,
        *,
        registry_entity: str,
        keep_asset_ids: Iterable[str],
    ) -> int:
        keep = set(keep_asset_ids)
        result = await self.session.execute(
            select(SystemAsset).where(SystemAsset.owner_scope == "system")
        )
        archived = 0
        for asset in result.scalars().all():
            metadata = asset.metadata_json if isinstance(asset.metadata_json, dict) else {}
            if metadata.get("registry_entity") != registry_entity:
                continue
            if asset.asset_id in keep or asset.status == "archived":
                continue
            asset.status = "archived"
            self.session.add(asset)
            archived += 1

        if archived:
            await self.session.flush()

        return archived


__all__ = ["SystemAssetRepository"]
