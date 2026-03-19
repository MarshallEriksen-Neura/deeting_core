from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.deps.superuser import get_current_superuser
from app.schemas.dashboard import PendingReviewCountsResponse
from app.services.dashboard.dashboard_service import DashboardService

router = APIRouter(prefix="/admin", tags=["Admin - Dashboard"])

DbSession = Annotated[AsyncSession, Depends(get_db)]


def get_service(db: DbSession) -> DashboardService:
    return DashboardService(db)


DashboardServiceDep = Annotated[DashboardService, Depends(get_service)]
SuperuserDep = Annotated[object, Depends(get_current_superuser)]


@router.get("/pending-reviews", response_model=PendingReviewCountsResponse)
async def get_pending_review_counts(
    _: SuperuserDep,
    service: DashboardServiceDep,
) -> PendingReviewCountsResponse:
    return await service.get_pending_review_counts()

