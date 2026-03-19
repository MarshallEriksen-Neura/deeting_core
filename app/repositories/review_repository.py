from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select

from app.models.review import ReviewTask

from .base import BaseRepository


class ReviewTaskRepository(BaseRepository[ReviewTask]):
    model = ReviewTask

    async def get_by_entity(
        self, entity_type: str, entity_id: UUID
    ) -> ReviewTask | None:
        result = await self.session.execute(
            select(ReviewTask).where(
                ReviewTask.entity_type == entity_type,
                ReviewTask.entity_id == entity_id,
            )
        )
        return result.scalars().first()

    async def list_by_status(self, entity_type: str, status: str) -> list[ReviewTask]:
        result = await self.session.execute(
            select(ReviewTask).where(
                ReviewTask.entity_type == entity_type,
                ReviewTask.status == status,
            )
        )
        return list(result.scalars().all())

    async def count_by_status(self, entity_type: str, status: str) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(ReviewTask).where(
                ReviewTask.entity_type == entity_type,
                ReviewTask.status == status,
            )
        )
        return int(result.scalar() or 0)

    def build_query(
        self,
        *,
        entity_type: str | None = None,
        status: str | None = None,
    ):
        stmt = select(ReviewTask)
        if entity_type:
            stmt = stmt.where(ReviewTask.entity_type == entity_type)
        if status:
            stmt = stmt.where(ReviewTask.status == status)
        return stmt.order_by(ReviewTask.created_at.desc(), ReviewTask.id.desc())
