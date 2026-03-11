from __future__ import annotations

import logging
import uuid

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.celery_app import celery_app
from app.models import User
from app.models.skill_registry import SkillRegistry
from app.models.user_skill_installation import UserSkillInstallation
from app.repositories.skill_registry_repository import SkillRegistryRepository
from app.repositories.user_skill_installation_repository import (
    UserSkillInstallationRepository,
)
from app.services.system_assets import SystemAssetRegistryService
from app.utils.security import is_safe_upstream_url

logger = logging.getLogger(__name__)


class PluginMarketService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.skill_repo = SkillRegistryRepository(session)
        self.install_repo = UserSkillInstallationRepository(session)

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
            if policy.materialization_state == "hidden":
                continue
            if keyword:
                haystack = " ".join(
                    [
                        asset.asset_id,
                        asset.title or "",
                        asset.description or "",
                        str(metadata.get("skill_id") or ""),
                    ]
                ).lower()
                if keyword.lower() not in haystack:
                    continue
            filtered_assets.append(asset)

        filtered_assets.sort(key=lambda item: ((item.title or "").lower(), item.asset_id))
        filtered_assets = filtered_assets[: max(1, min(limit, 100))]

        installed_ids = await self.install_repo.list_enabled_skill_ids(user.id)
        return [
            (
                asset,
                str((asset.metadata_json or {}).get("skill_id") or "") in installed_ids,
            )
            for asset in filtered_assets
        ]

    async def list_installations(self, *, user_id: uuid.UUID) -> list[UserSkillInstallation]:
        return await self.install_repo.list_by_user(user_id, enabled_only=False)

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

    async def install_skill(
        self,
        *,
        user_id: uuid.UUID,
        skill_id: str,
        alias: str | None = None,
        config_json: dict | None = None,
    ) -> tuple[UserSkillInstallation, bool]:
        skill = await self.skill_repo.get_by_id(skill_id)
        if not skill:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="plugin not found")
        if skill.type == "BUILTIN":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="builtin skill cannot be installed via plugin market",
            )
        if skill.status != "active":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="plugin is not active",
            )

        manifest = skill.manifest_json if isinstance(skill.manifest_json, dict) else {}
        permissions = manifest.get("permissions")
        if not isinstance(permissions, list):
            permissions = []
        permission_list = [str(item) for item in permissions if item is not None]
        existing = await self.install_repo.get_by_user_skill(user_id, skill_id)
        if existing:
            if alias is not None:
                existing.alias = alias
            if config_json is not None:
                existing.config_json = config_json
            if permission_list:
                existing.granted_permissions = permission_list
            existing.installed_revision = skill.source_revision
            existing.is_enabled = True
            await self.session.flush()
            await self.session.refresh(existing)
            return existing, False

        installation = await self.install_repo.create(
            user_id=user_id,
            skill_id=skill_id,
            alias=alias,
            config_json=config_json or {},
            granted_permissions=permission_list,
            installed_revision=skill.source_revision,
            is_enabled=True,
        )
        return installation, True

    async def uninstall_skill(self, *, user_id: uuid.UUID, skill_id: str) -> bool:
        deleted = await self.install_repo.delete_by_user_skill(user_id, skill_id)

        try:
            from app.services.tools.tool_sync_service import tool_sync_service

            await tool_sync_service.remove_user_skill_embeddings(user_id, skill_id)
        except Exception:
            logger.warning(
                "failed to cleanup skill embeddings user=%s skill=%s",
                user_id,
                skill_id,
                exc_info=True,
            )

        return deleted
