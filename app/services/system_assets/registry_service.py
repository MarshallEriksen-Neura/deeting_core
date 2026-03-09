from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assistant import Assistant, AssistantStatus, AssistantVersion, AssistantVisibility
from app.models import Role, User, UserRole
from app.models.skill_registry import SkillRegistry
from app.models.system_asset import SystemAsset
from app.repositories.system_asset_repository import SystemAssetRepository
from app.repositories.user_skill_installation_repository import (
    UserSkillInstallationRepository,
)
from app.schemas.system_asset import (
    SystemAssetPolicySnapshot,
    SystemAssetSyncItem,
)


class SystemAssetRegistryService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = SystemAssetRepository(session)

    async def list_sync_items(
        self,
        *,
        user: User,
        asset_kind: str | None = None,
        limit: int = 100,
    ) -> list[SystemAssetSyncItem]:
        await self.sync_projection_sources()
        assets = await self.repo.list_system_assets(
            asset_kind=asset_kind,
            status="active",
            limit=limit,
        )
        role_names = await self._fetch_user_role_names(user_id=user.id)
        skill_install_map = await self._fetch_user_skill_install_map(user_id=user.id)
        items: list[SystemAssetSyncItem] = []
        for asset in assets:
            policy = self._build_policy_snapshot(asset=asset, user=user, role_names=role_names)
            if policy.materialization_state == "hidden":
                continue
            items.append(
                SystemAssetSyncItem(
                    asset_id=asset.asset_id,
                    title=asset.title,
                    description=asset.description,
                    asset_kind=asset.asset_kind,
                    owner_scope=asset.owner_scope,
                    source_kind=asset.source_kind,
                    version=asset.version,
                    artifact_ref=asset.artifact_ref,
                    checksum=asset.checksum,
                    metadata_json=self._build_sync_metadata(
                        asset=asset,
                        skill_install_map=skill_install_map,
                    ),
                    policy_snapshot=policy,
                )
            )
        return items

    async def list_visible_system_assistant_ids(self, *, user: User) -> set[UUID]:
        await self.sync_projection_sources()
        assets = await self.repo.list_system_assets(
            asset_kind="capability",
            status="active",
            limit=1000,
        )
        role_names = await self._fetch_user_role_names(user_id=user.id)
        assistant_ids: set[UUID] = set()
        for asset in assets:
            metadata = asset.metadata_json if isinstance(asset.metadata_json, dict) else {}
            if metadata.get("registry_entity") != "assistant":
                continue
            policy = self._build_policy_snapshot(
                asset=asset,
                user=user,
                role_names=role_names,
            )
            if policy.materialization_state == "hidden":
                continue
            raw_id = metadata.get("assistant_id")
            if not raw_id:
                continue
            try:
                assistant_ids.add(UUID(str(raw_id)))
            except Exception:
                continue
        return assistant_ids

    async def sync_projection_sources(self) -> None:
        await self.sync_skill_registry_projections()
        await self.sync_system_assistant_projections()
        await self.session.commit()

    async def sync_skill_registry_projections(self) -> None:
        result = await self.session.execute(
            select(SkillRegistry).where(
                SkillRegistry.status == "active",
                SkillRegistry.type != "BUILTIN",
            )
        )
        skills = list(result.scalars().all())
        for skill in skills:
            manifest = skill.manifest_json if isinstance(skill.manifest_json, dict) else {}
            restricted = bool(manifest.get("restricted"))
            allowed_roles = [str(item) for item in manifest.get("allowed_roles") or []]
            visibility_scope = "authenticated"
            if restricted:
                visibility_scope = "role" if allowed_roles else "superuser"
            manifest_id = str(manifest.get("id") or skill.id)
            source_kind = "official" if manifest_id.startswith("official.") else "community"
            existing = await self.repo.get_by_asset_id(f"skill:{skill.id}")
            policy = self._merge_projection_policy(
                existing=existing,
                defaults={
                    "status": "active",
                    "visibility_scope": visibility_scope,
                    "local_sync_policy": "full",
                    "execution_policy": "allowed",
                    "permission_grants": [
                        str(item) for item in manifest.get("permissions") or []
                    ],
                    "allowed_role_names": allowed_roles,
                },
            )
            await self.repo.upsert_asset(
                asset_id=f"skill:{skill.id}",
                obj_in={
                    "title": skill.name,
                    "description": skill.description,
                    "asset_kind": "capability",
                    "owner_scope": "system",
                    "source_kind": source_kind,
                    "version": skill.version or "0.0.0",
                    "artifact_ref": skill.source_repo,
                    "checksum": skill.source_revision,
                    "metadata_json": {
                        "registry_entity": "skill",
                        "skill_id": skill.id,
                        "skill_type": skill.type,
                        "runtime": skill.runtime,
                        "manifest": manifest,
                    },
                    **policy,
                },
            )

    async def sync_system_assistant_projections(self) -> None:
        result = await self.session.execute(
            select(Assistant, AssistantVersion)
            .join(AssistantVersion, Assistant.current_version_id == AssistantVersion.id)
            .where(
                Assistant.owner_user_id.is_(None),
                Assistant.status == AssistantStatus.PUBLISHED,
            )
        )
        rows = result.all()
        for assistant, version in rows:
            visibility = (
                assistant.visibility.value
                if isinstance(assistant.visibility, AssistantVisibility)
                else str(assistant.visibility)
            )
            is_public = visibility == AssistantVisibility.PUBLIC.value
            asset_id = f"assistant:{assistant.id}"
            existing = await self.repo.get_by_asset_id(asset_id)
            policy = self._merge_projection_policy(
                existing=existing,
                defaults={
                    "status": "active",
                    "visibility_scope": "authenticated" if is_public else "internal",
                    "local_sync_policy": "full" if is_public else "metadata_only",
                    "execution_policy": "allowed",
                    "permission_grants": [],
                    "allowed_role_names": [],
                },
            )
            await self.repo.upsert_asset(
                asset_id=asset_id,
                obj_in={
                    "title": version.name,
                    "description": version.description or assistant.summary,
                    "asset_kind": "capability",
                    "owner_scope": "system",
                    "source_kind": "official",
                    "version": version.version,
                    "artifact_ref": assistant.share_slug,
                    "checksum": str(version.id),
                    "metadata_json": {
                        "registry_entity": "assistant",
                        "assistant_id": str(assistant.id),
                        "current_version_id": str(version.id),
                        "summary": assistant.summary,
                        "icon_id": assistant.icon_id,
                        "share_slug": assistant.share_slug,
                        "published_at": self._datetime_to_iso(assistant.published_at),
                        "install_count": int(assistant.install_count or 0),
                        "rating_avg": float(assistant.rating_avg or 0.0),
                        "rating_count": int(assistant.rating_count or 0),
                        "version": {
                            "id": str(version.id),
                            "version": version.version,
                            "name": version.name,
                            "description": version.description,
                            "system_prompt": version.system_prompt,
                            "tags": version.tags or [],
                            "published_at": self._datetime_to_iso(version.published_at),
                        },
                    },
                    **policy,
                },
            )

    @staticmethod
    def _merge_projection_policy(
        *,
        existing: SystemAsset | None,
        defaults: dict,
    ) -> dict:
        if existing is None:
            return defaults
        return {
            "status": existing.status or defaults["status"],
            "visibility_scope": existing.visibility_scope or defaults["visibility_scope"],
            "local_sync_policy": existing.local_sync_policy or defaults["local_sync_policy"],
            "execution_policy": existing.execution_policy or defaults["execution_policy"],
            "permission_grants": existing.permission_grants
            if existing.permission_grants is not None
            else defaults["permission_grants"],
            "allowed_role_names": existing.allowed_role_names
            if existing.allowed_role_names is not None
            else defaults["allowed_role_names"],
        }

    async def _fetch_user_skill_install_map(self, *, user_id: UUID) -> dict[str, object]:
        installs = await UserSkillInstallationRepository(self.session).list_by_user(
            user_id,
            enabled_only=False,
        )
        return {str(install.skill_id): install for install in installs if install.skill_id}

    def _build_sync_metadata(
        self,
        *,
        asset: SystemAsset,
        skill_install_map: dict[str, object],
    ) -> dict:
        metadata = dict(asset.metadata_json or {}) if isinstance(asset.metadata_json, dict) else {}
        if metadata.get("registry_entity") != "skill":
            return metadata

        skill_id = str(metadata.get("skill_id") or "").strip()
        if not skill_id:
            return metadata

        metadata["user_install"] = self._serialize_user_skill_install(
            skill_install_map.get(skill_id)
        )
        return metadata

    @staticmethod
    def _serialize_user_skill_install(install: object | None) -> dict | None:
        if install is None:
            return None
        return {
            "alias": getattr(install, "alias", None),
            "config_json": getattr(install, "config_json", {}) or {},
            "granted_permissions": list(getattr(install, "granted_permissions", []) or []),
            "installed_revision": getattr(install, "installed_revision", None),
            "is_enabled": bool(getattr(install, "is_enabled", False)),
        }

    @staticmethod
    def _datetime_to_iso(value) -> str | None:
        if value is None:
            return None
        try:
            return value.isoformat()
        except Exception:
            return str(value)

    async def _fetch_user_role_names(self, *, user_id) -> set[str]:
        stmt = (
            select(Role.name)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user_id)
        )
        result = await self.session.execute(stmt)
        return {name for name in result.scalars().all() if name}

    def _build_policy_snapshot(
        self,
        *,
        asset: SystemAsset,
        user: User,
        role_names: set[str],
    ) -> SystemAssetPolicySnapshot:
        visible = self._is_visible(asset=asset, user=user, role_names=role_names)
        materialization_state = self._resolve_materialization_state(
            asset=asset,
            visible=visible,
        )
        return SystemAssetPolicySnapshot(
            visibility_scope=asset.visibility_scope,
            local_sync_policy=asset.local_sync_policy,
            execution_policy=asset.execution_policy,
            permission_grants=asset.permission_grants or [],
            allowed_role_names=asset.allowed_role_names or [],
            materialization_state=materialization_state,
        )

    @staticmethod
    def _is_visible(
        *,
        asset: SystemAsset,
        user: User,
        role_names: set[str],
    ) -> bool:
        if bool(user.is_superuser):
            return True
        scope = asset.visibility_scope or "authenticated"
        if scope in {"public", "authenticated"}:
            return True
        if scope in {"superuser", "internal"}:
            return False
        if scope == "role":
            allowed = set(asset.allowed_role_names or [])
            return bool(allowed and allowed.intersection(role_names))
        return True

    @staticmethod
    def _resolve_materialization_state(*, asset: SystemAsset, visible: bool) -> str:
        if not visible or asset.local_sync_policy in {"none", "hidden"}:
            return "hidden"
        if asset.local_sync_policy == "metadata_only":
            return "metadata_only"
        if asset.execution_policy in {"deny", "approval_required"}:
            return "metadata_only"
        return "executable"
