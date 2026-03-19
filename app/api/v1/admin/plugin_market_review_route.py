from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.deps.superuser import get_current_superuser
from app.schemas.admin_ops import (
    PluginMarketReviewAdminItem,
    PluginMarketReviewAdminListResponse,
    PluginMarketReviewDecisionRequest,
)
from app.services.admin import PluginMarketReviewAdminService

router = APIRouter(prefix="/admin/plugin-reviews", tags=["Admin - Plugin Reviews"])


def get_service(
    db: AsyncSession = Depends(get_db),
) -> PluginMarketReviewAdminService:
    return PluginMarketReviewAdminService(db)


@router.get("", response_model=PluginMarketReviewAdminListResponse)
async def list_plugin_market_reviews(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    status_filter: str | None = Query(default=None),
    _=Depends(get_current_superuser),
    service: PluginMarketReviewAdminService = Depends(get_service),
) -> PluginMarketReviewAdminListResponse:
    return await service.list_reviews(
        skip=skip,
        limit=limit,
        status_filter=status_filter,
    )


@router.post("/{skill_id}/approve", response_model=PluginMarketReviewAdminItem)
async def approve_plugin_market_review(
    skill_id: str,
    payload: PluginMarketReviewDecisionRequest,
    current_user=Depends(get_current_superuser),
    service: PluginMarketReviewAdminService = Depends(get_service),
) -> PluginMarketReviewAdminItem:
    return await service.approve_review(
        skill_id,
        reviewer_user_id=current_user.id,
        reason=payload.reason,
    )


@router.post("/{skill_id}/reject", response_model=PluginMarketReviewAdminItem)
async def reject_plugin_market_review(
    skill_id: str,
    payload: PluginMarketReviewDecisionRequest,
    current_user=Depends(get_current_superuser),
    service: PluginMarketReviewAdminService = Depends(get_service),
) -> PluginMarketReviewAdminItem:
    return await service.reject_review(
        skill_id,
        reviewer_user_id=current_user.id,
        reason=payload.reason,
    )

