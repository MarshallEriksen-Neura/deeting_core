from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.deps.auth import get_current_user
from app.schemas.auth import MessageResponse
from app.schemas.plugin_market import (
    PluginInstallationItem,
    PluginInstallRequest,
    PluginMarketSkillItem,
    PluginSubmitRequest,
    PluginSubmitResponse,
    PluginUiSessionRequest,
    PluginUiSessionResponse,
)
from app.services.plugin_market_service import PluginMarketService
from app.services.plugin_ui_gateway_service import PluginUiGatewayService

router = APIRouter(prefix="/plugin-market", tags=["Plugin Market"])


@router.get("/plugins", response_model=list[PluginMarketSkillItem])
async def list_plugins(
    q: str | None = Query(None, description="搜索关键字"),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> list[PluginMarketSkillItem]:
    service = PluginMarketService(db)
    rows = await service.list_market_skills(user=user, q=q, limit=limit)
    return [
        PluginMarketSkillItem(
            id=str((skill.metadata_json or {}).get("skill_id") or skill.asset_id),
            name=skill.title,
            description=skill.description,
            version=skill.version,
            source_repo=skill.artifact_ref,
            source_revision=skill.checksum,
            source_kind=skill.source_kind,
            status=skill.status,
            installed=installed,
            compatibility=(skill.metadata_json or {}).get("manifest", {}).get("compatibility")
            if isinstance((skill.metadata_json or {}).get("manifest"), dict)
            else None,
            created_at=skill.created_at,
            updated_at=skill.updated_at,
        )
        for skill, installed in rows
    ]


@router.get("/installs", response_model=list[PluginInstallationItem])
async def list_installs(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> list[PluginInstallationItem]:
    return []


@router.post("/plugins/submit", response_model=PluginSubmitResponse)
async def submit_plugin_repo(
    payload: PluginSubmitRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> PluginSubmitResponse:
    service = PluginMarketService(db)
    task_id = await service.submit_repo(
        user_id=user.id,
        repo_url=str(payload.repo_url),
        revision=payload.revision,
        skill_id=payload.skill_id,
        runtime_hint=payload.runtime_hint,
    )
    return PluginSubmitResponse(status="queued", task_id=task_id)


@router.post(
    "/plugins/{skill_id}/install",
    response_model=PluginInstallationItem,
    status_code=status.HTTP_201_CREATED,
)
async def install_plugin(
    skill_id: str,
    payload: PluginInstallRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> PluginInstallationItem:
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail=(
            "Cloud plugin installs are no longer supported. "
            "Install plugins from the desktop app instead."
        ),
    )


@router.delete("/plugins/{skill_id}/install", response_model=MessageResponse)
async def uninstall_plugin(
    skill_id: str,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> MessageResponse:
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail=(
            "Cloud plugin installs are no longer supported. "
            "Uninstall plugins from the desktop app instead."
        ),
    )


@router.post(
    "/plugins/{skill_id}/ui/session",
    response_model=PluginUiSessionResponse,
)
async def issue_plugin_ui_session(
    skill_id: str,
    payload: PluginUiSessionRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> PluginUiSessionResponse:
    service = PluginUiGatewayService(db)
    session = await service.issue_renderer_session(
        user_id=user.id,
        skill_id=skill_id,
        base_url=str(request.base_url).rstrip("/"),
        ttl_seconds=payload.ttl_seconds,
    )
    return PluginUiSessionResponse(
        skill_id=session.skill_id,
        revision=session.revision,
        renderer_asset_path=session.renderer_asset_path,
        renderer_url=session.renderer_url,
        expires_at=session.expires_at,
    )


@router.get("/ui/t/{token}/{asset_path:path}")
async def get_plugin_ui_asset(
    token: str,
    asset_path: str,
) -> FileResponse:
    service = PluginUiGatewayService()
    asset = await service.resolve_asset(token=token, asset_path=asset_path)
    max_age = max(0, min(300, int(asset.expires_at) - int(time.time())))
    cache_control = f"private, max-age={max_age}" if max_age > 0 else "no-store"
    return FileResponse(
        path=str(asset.file_path),
        media_type=asset.content_type,
        headers={"Cache-Control": cache_control},
    )
