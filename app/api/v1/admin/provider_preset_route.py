
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache_invalidation import CacheInvalidator
from app.core.database import get_db
from app.core.logging import logger
from app.deps.superuser import get_current_superuser
from app.models.provider_preset import ProviderPreset
from app.repositories.provider_preset_repository import ProviderPresetRepository
from app.schemas.provider_preset import (
    ProviderPresetDTO,
    ProviderPresetDesktopUpsertRequest,
    ProviderPresetDesktopUpsertResponse,
    ProviderWish,
)
from app.tasks.search_index import upsert_provider_preset_task

router = APIRouter(prefix="/admin/provider-presets", tags=["ProviderPresets"])


@router.get("", response_model=list[ProviderPresetDTO])
async def list_presets(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_superuser),
):
    repo = ProviderPresetRepository(db)
    presets = await repo.get_active_presets()
    return presets


@router.post("/wishes", status_code=status.HTTP_202_ACCEPTED)
async def wish_provider(
    payload: ProviderWish,
    user=Depends(get_current_superuser),
):
    """
    Submit a wish for a new provider.
    Currently just logs the wish, but can be extended to store in DB.
    """
    logger.info(
        "provider_wish_submitted",
        extra={
            "user_id": str(user.id),
            "provider_name": payload.provider_name,
            "url": payload.url,
            "description": payload.description,
        },
    )
    return {"message": "Wish received"}


@router.post("/upsert-from-desktop", response_model=ProviderPresetDesktopUpsertResponse)
async def upsert_provider_preset_from_desktop(
    payload: ProviderPresetDesktopUpsertRequest,
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_superuser),
):
    preset_payload = payload.preset.model_dump()
    slug = str(preset_payload.get("slug") or "").strip()
    name = str(preset_payload.get("name") or "").strip()
    provider = str(preset_payload.get("provider") or "").strip()
    base_url = str(preset_payload.get("base_url") or "").strip()

    if not slug or not name or not provider or not base_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="slug, name, provider, and base_url are required",
        )

    repo = ProviderPresetRepository(db)
    existing = await repo.get_by_slug(slug)
    normalized_payload = {
        "slug": slug,
        "name": name,
        "provider": provider,
        "category": preset_payload.get("category"),
        "base_url": base_url,
        "url_template": preset_payload.get("url_template"),
        "theme_color": preset_payload.get("theme_color"),
        "icon": preset_payload.get("icon") or "lucide:cpu",
        "auth_type": preset_payload.get("auth_type") or "api_key",
        "auth_config": preset_payload.get("auth_config") or {},
        "protocol_schema_version": preset_payload.get("protocol_schema_version"),
        "protocol_profiles": preset_payload.get("protocol_profiles") or {},
        "version": int(preset_payload.get("version") or 1),
        "is_active": bool(preset_payload.get("is_active", True)),
    }

    if existing is None:
        db.add(ProviderPreset(**normalized_payload))
        updated = False
    else:
        updated = True
        for key, value in normalized_payload.items():
            setattr(existing, key, value)
        db.add(existing)

    await db.commit()
    await CacheInvalidator().on_preset_updated(slug)
    upsert_provider_preset_task.delay(slug)

    return ProviderPresetDesktopUpsertResponse(
        status="ok",
        slug=slug,
        updated=updated,
    )
