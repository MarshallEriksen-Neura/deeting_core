from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.celery_app import celery_app
from app.models.skill_registry import SkillRegistry
from app.repositories.skill_registry_repository import SkillRegistryRepository
from app.utils.security import is_safe_upstream_url


class PluginMarketService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.skill_repo = SkillRegistryRepository(session)

    async def list_market_skills(
        self, *, user_id: uuid.UUID, q: str | None = None, limit: int = 50
    ) -> list[tuple[SkillRegistry, bool]]:
        stmt = select(SkillRegistry).where(
            SkillRegistry.status == "active",
        )
        keyword = (q or "").strip()
        if keyword:
            like = f"%{keyword}%"
            stmt = stmt.where(
                or_(
                    SkillRegistry.id.ilike(like),
                    SkillRegistry.name.ilike(like),
                    SkillRegistry.description.ilike(like),
                )
            )
        stmt = stmt.order_by(SkillRegistry.updated_at.desc(), SkillRegistry.id.asc())
        stmt = stmt.limit(max(1, min(limit, 100)))
        result = await self.session.execute(stmt)
        skills = list(result.scalars().all())

        # Cloud plugin installs are no longer a supported product path.
        # Desktop computes install state from local storage instead.
        return [(skill, False) for skill in skills]

    async def submit_repo(
        self,
        *,
        user_id: uuid.UUID,
        repo_url: str,
        revision: str = "main",
        skill_id: str | None = None,
        runtime_hint: str | None = None,
    ) -> str:
        if not is_safe_upstream_url(repo_url):
            raise HTTPException(status_code=400, detail="unsafe repo_url")
        task = celery_app.send_task(
            "skill_registry.ingest_repo",
            args=[repo_url, revision, skill_id, runtime_hint, str(user_id)],
        )
        return str(task.id)
