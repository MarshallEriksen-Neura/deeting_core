from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.celery_app import celery_app
from app.models import User
from app.models.skill_registry import SkillRegistry
from app.repositories.skill_registry_repository import SkillRegistryRepository
from app.utils.security import is_safe_upstream_url


class PluginMarketService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.skill_repo = SkillRegistryRepository(session)

    async def list_market_skills(
        self, *, user: User, q: str | None = None, limit: int = 50
    ) -> list[tuple[SkillRegistry, bool]]:
        registry_service = SystemAssetRegistryService(self.session)
        await registry_service.sync_projection_sources()
        role_names = await registry_service._fetch_user_role_names(user_id=user.id)
        assets = await registry_service.repo.list_system_assets(
            asset_kind="skill_bundle",
            status="active",
            limit=max(200, limit * 5),
        )
        keyword = (q or "").strip()
        filtered_assets = []
        for asset in assets:
            metadata = asset.metadata_json if isinstance(asset.metadata_json, dict) else {}
            if metadata.get("registry_entity") != "skill":
                continue
            policy = registry_service._build_policy_snapshot(
                asset=asset,
                user=user,
                role_names=role_names,
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
            kwargs={
                "repo_url": repo_url,
                "revision": revision,
                "skill_id": skill_id,
                "runtime_hint": runtime_hint,
                "source_subdir": None,
                "user_id": str(user_id),
                "submission_channel": "plugin_market",
            },
        )
        return str(task.id)
