from __future__ import annotations

from uuid import UUID, uuid4

import pytest


async def _seed_system_asset(session, **overrides):
    from app.models.system_asset import SystemAsset

    asset_id = overrides.pop("asset_id", f"system.asset.{uuid4().hex}")
    asset = SystemAsset(
        asset_id=asset_id,
        title=overrides.pop("title", "System Asset"),
        description=overrides.pop("description", "desc"),
        asset_kind=overrides.pop("asset_kind", "capability"),
        owner_scope=overrides.pop("owner_scope", "system"),
        source_kind=overrides.pop("source_kind", "official"),
        version=overrides.pop("version", "0.1.0"),
        status=overrides.pop("status", "active"),
        visibility_scope=overrides.pop("visibility_scope", "authenticated"),
        local_sync_policy=overrides.pop("local_sync_policy", "full"),
        execution_policy=overrides.pop("execution_policy", "allowed"),
        permission_grants=overrides.pop("permission_grants", ["network_read"]),
        allowed_role_names=overrides.pop("allowed_role_names", []),
        artifact_ref=overrides.pop("artifact_ref", None),
        checksum=overrides.pop("checksum", None),
        metadata_json=overrides.pop("metadata_json", {"origin": "test"}),
        **overrides,
    )
    session.add(asset)
    await session.commit()
    await session.refresh(asset)
    return asset


async def _seed_market_skill(session, *, skill_id: str, name: str = "Projected Skill"):
    from app.models.skill_registry import SkillRegistry

    skill = SkillRegistry(
        id=skill_id,
        name=name,
        description="skill desc",
        version="1.0.0",
        status="active",
        type="SKILL",
        manifest_json={"id": skill_id, "permissions": ["network_read"]},
        env_requirements={},
    )
    session.add(skill)
    await session.commit()
    await session.refresh(skill)
    return skill


async def _seed_skill_install(
    session,
    *,
    user_id: str,
    skill_id: str,
    alias: str = "desktop-installed",
):
    from app.models.user_skill_installation import UserSkillInstallation

    install = UserSkillInstallation(
        user_id=UUID(user_id),
        skill_id=skill_id,
        alias=alias,
        config_json={"region": "global"},
        granted_permissions=["network_read"],
        installed_revision="rev-123",
        is_enabled=True,
    )
    session.add(install)
    await session.commit()
    await session.refresh(install)
    return install


async def _seed_system_assistant(session, *, suffix: str):
    from app.models.assistant import (
        Assistant,
        AssistantStatus,
        AssistantVersion,
        AssistantVisibility,
    )

    assistant_id = uuid4()
    version_id = uuid4()
    assistant = Assistant(
        id=assistant_id,
        owner_user_id=None,
        visibility=AssistantVisibility.PUBLIC,
        status=AssistantStatus.PUBLISHED,
        current_version_id=version_id,
        summary="system assistant",
    )
    version = AssistantVersion(
        id=version_id,
        assistant_id=assistant_id,
        version="0.1.0",
        name=f"System Assistant {suffix}",
        description="assistant desc",
        system_prompt="prompt",
        model_config={},
        skill_refs=[],
        tags=[],
    )
    assistant.current_version_id = version.id
    session.add_all([assistant, version])
    await session.commit()
    await session.refresh(assistant)
    return assistant, version


async def _seed_approved_user_assistant(session, *, user_id: str, suffix: str):
    from app.models.assistant import (
        Assistant,
        AssistantStatus,
        AssistantVersion,
        AssistantVisibility,
    )
    from app.models.review import ReviewStatus, ReviewTask
    from app.services.assistant.constants import ASSISTANT_MARKET_ENTITY

    assistant_id = uuid4()
    version_id = uuid4()
    assistant = Assistant(
        id=assistant_id,
        owner_user_id=UUID(user_id),
        visibility=AssistantVisibility.PUBLIC,
        status=AssistantStatus.PUBLISHED,
        current_version_id=version_id,
        summary="approved user assistant",
    )
    version = AssistantVersion(
        id=version_id,
        assistant_id=assistant_id,
        version="0.1.0",
        name=f"Approved User Assistant {suffix}",
        description="assistant desc",
        system_prompt="prompt",
        model_config={},
        skill_refs=[],
        tags=[],
    )
    review = ReviewTask(
        entity_type=ASSISTANT_MARKET_ENTITY,
        entity_id=assistant_id,
        submitter_user_id=UUID(user_id),
        reviewer_user_id=UUID(user_id),
        status=ReviewStatus.APPROVED.value,
        reason="approved",
    )
    assistant.current_version_id = version.id
    session.add_all([assistant, version, review])
    await session.commit()
    await session.refresh(assistant)
    return assistant, version


@pytest.mark.asyncio
async def test_system_asset_sync_resolves_materialization_for_regular_user(
    client,
    auth_tokens: dict,
    AsyncSessionLocal,
) -> None:
    public_id = f"system.capability.public-search.{uuid4().hex}"
    requestable_id = f"system.capability.request-review.{uuid4().hex}"
    admin_id = f"system.capability.admin-console.{uuid4().hex}"

    async with AsyncSessionLocal() as session:
        await _seed_system_asset(session, asset_id=public_id, title="Public Search")
        await _seed_system_asset(
            session,
            asset_id=requestable_id,
            title="Request Review",
            local_sync_policy="metadata_only",
        )
        await _seed_system_asset(
            session,
            asset_id=admin_id,
            title="Admin Console",
            visibility_scope="superuser",
        )

    resp = await client.get(
        "/api/v1/system-assets/sync?asset_kind=capability",
        headers={"Authorization": f"Bearer {auth_tokens['access_token']}"},
    )
    assert resp.status_code == 200

    items = {item["asset_id"]: item for item in resp.json()["items"]}
    assert items[public_id]["policy_snapshot"]["materialization_state"] == "executable"
    assert (
        items[requestable_id]["policy_snapshot"]["materialization_state"]
        == "metadata_only"
    )
    assert admin_id not in items


@pytest.mark.asyncio
async def test_system_asset_sync_exposes_superuser_assets_to_admin(
    client,
    admin_tokens: dict,
    AsyncSessionLocal,
) -> None:
    admin_id = f"system.capability.admin-only.{uuid4().hex}"

    async with AsyncSessionLocal() as session:
        await _seed_system_asset(
            session,
            asset_id=admin_id,
            title="Admin Only",
            visibility_scope="superuser",
        )

    resp = await client.get(
        "/api/v1/system-assets/sync?asset_kind=capability",
        headers={"Authorization": f"Bearer {admin_tokens['access_token']}"},
    )
    assert resp.status_code == 200

    items = {item["asset_id"]: item for item in resp.json()["items"]}
    assert items[admin_id]["policy_snapshot"]["materialization_state"] == "executable"
    assert items[admin_id]["policy_snapshot"]["visibility_scope"] == "superuser"


@pytest.mark.asyncio
async def test_system_asset_sync_projects_active_skill_registry_entries(
    client,
    auth_tokens: dict,
    test_user: dict,
    AsyncSessionLocal,
) -> None:
    skill_id = f"official.skills.monitor.{uuid4().hex}"

    async with AsyncSessionLocal() as session:
        await _seed_market_skill(session, skill_id=skill_id, name="Projected Monitor")
        await _seed_skill_install(session, user_id=test_user["id"], skill_id=skill_id)

    resp = await client.get(
        "/api/v1/system-assets/skills",
        headers={"Authorization": f"Bearer {auth_tokens['access_token']}"},
    )
    assert resp.status_code == 200
    items = {item["asset_id"]: item for item in resp.json()["items"]}
    projected_id = f"skill:{skill_id}"
    assert items[projected_id]["title"] == "Projected Monitor"
    assert items[projected_id]["metadata_json"]["registry_entity"] == "skill"
    assert items[projected_id]["metadata_json"]["user_install"]["alias"] == "desktop-installed"
    assert items[projected_id]["metadata_json"]["user_install"]["installed_revision"] == "rev-123"


@pytest.mark.asyncio
async def test_system_asset_sync_projects_system_assistants(
    client,
    auth_tokens: dict,
    AsyncSessionLocal,
) -> None:
    suffix = uuid4().hex[:8]
    async with AsyncSessionLocal() as session:
        assistant, version = await _seed_system_assistant(session, suffix=suffix)

    resp = await client.get(
        "/api/v1/system-assets/assistants",
        headers={"Authorization": f"Bearer {auth_tokens['access_token']}"},
    )
    assert resp.status_code == 200
    items = {item["asset_id"]: item for item in resp.json()["items"]}
    projected_id = f"assistant:{assistant.id}"
    assert items[projected_id]["title"] == version.name
    assert items[projected_id]["metadata_json"]["registry_entity"] == "assistant"
    assert items[projected_id]["metadata_json"]["version"]["id"] == str(version.id)
    assert items[projected_id]["metadata_json"]["version"]["name"] == version.name


@pytest.mark.asyncio
@pytest.mark.xfail(
    reason="SQLite test harness visibility differs from the real Postgres projection smoke; covered by backend/scripts real smoke.",
    strict=False,
)
async def test_system_asset_sync_projects_approved_user_assistants(
    test_user: dict,
    AsyncSessionLocal,
) -> None:
    from app.repositories.assistant_install_repository import AssistantInstallRepository
    from app.repositories.assistant_market_repository import AssistantMarketRepository
    from app.repositories.assistant_repository import (
        AssistantRepository,
        AssistantVersionRepository,
    )
    from app.repositories.review_repository import ReviewTaskRepository
    from app.repositories.user_repository import UserRepository
    from app.schemas.assistant import AssistantCreate, AssistantVersionCreate
    from app.services.assistant.assistant_market_service import AssistantMarketService
    from app.services.assistant.assistant_service import AssistantService

    suffix = uuid4().hex[:8]
    async with AsyncSessionLocal() as session:
        assistant_repo = AssistantRepository(session)
        version_repo = AssistantVersionRepository(session)
        assistant_service = AssistantService(assistant_repo, version_repo)
        market_service = AssistantMarketService(
            assistant_repo,
            AssistantInstallRepository(session),
            ReviewTaskRepository(session),
            AssistantMarketRepository(session),
        )
        reviewer = await UserRepository(session).get_primary_superuser()
        owner_user_id = reviewer.id if reviewer else UUID(test_user["id"])
        assistant = await assistant_service.create_assistant(
            payload=AssistantCreate(
                visibility="public",
                status="published",
                share_to_market=False,
                summary=f"user assistant {suffix}",
                icon_id="lucide:bot",
                version=AssistantVersionCreate(
                    name=f"Approved User Assistant {suffix}",
                    description="assistant desc",
                    system_prompt="prompt",
                    model_config={},
                    tags=[],
                ),
                ),
            owner_user_id=owner_user_id,
        )
        await market_service.submit_for_review(
            user_id=owner_user_id,
            assistant_id=assistant.id,
            payload={"source": "test"},
        )
        await market_service.approve_review(
            assistant_id=assistant.id,
            reviewer_user_id=owner_user_id,
            reason="approved",
        )
        await session.commit()
        version = await version_repo.get_for_assistant(assistant.id, assistant.current_version_id)

        from app.services.system_assets import SystemAssetRegistryService

        items = {
            item.asset_id: item
            for item in await SystemAssetRegistryService(session).list_assistant_sync_items(
                user=reviewer,
                limit=200,
            )
        }
    projected_id = f"assistant:{assistant.id}"
    assert projected_id in items
    assert items[projected_id].title == version.name
    assert items[projected_id].metadata_json["registry_entity"] == "assistant"
    assert items[projected_id].owner_scope == "user"
    assert items[projected_id].source_kind == "community"
