from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.deps.auth import get_current_user
from app.schemas.system_asset import SystemAssetSyncResponse
from app.services.system_assets import SystemAssetRegistryService

router = APIRouter(prefix="/system-assets", tags=["System Assets"])


@router.get("/assistants", response_model=SystemAssetSyncResponse)
async def sync_assistant_assets(
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> SystemAssetSyncResponse:
    service = SystemAssetRegistryService(db)
    items = await service.list_assistant_sync_items(user=user, limit=limit)
    return SystemAssetSyncResponse(items=items)


@router.get("/sync", response_model=SystemAssetSyncResponse)
async def sync_generic_system_assets(
    asset_kind: str | None = Query(None, description="Filter by asset kind"),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> SystemAssetSyncResponse:
    service = SystemAssetRegistryService(db)
    items = await service.list_generic_sync_items(
        user=user,
        asset_kind=asset_kind,
        limit=limit,
    )
    return SystemAssetSyncResponse(items=items)


@router.get("/skills", response_model=SystemAssetSyncResponse)
async def sync_skill_assets(
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> SystemAssetSyncResponse:
    service = SystemAssetRegistryService(db)
    items = await service.list_skill_sync_items(user=user, limit=limit)
    return SystemAssetSyncResponse(items=items)
