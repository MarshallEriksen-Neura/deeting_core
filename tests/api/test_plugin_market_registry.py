from __future__ import annotations

from uuid import UUID, uuid4

import pytest


async def _seed_market_skill(
    session,
    *,
    skill_id: str,
    name: str,
    restricted: bool = False,
    allowed_roles: list[str] | None = None,
):
    from app.models.skill_registry import SkillRegistry

    manifest = {"id": skill_id, "permissions": ["network_read"]}
    if restricted:
        manifest["restricted"] = True
        manifest["allowed_roles"] = allowed_roles or ["admin"]

    skill = SkillRegistry(
        id=skill_id,
        name=name,
        description="desc",
        version="1.0.0",
        status="active",
        type="SKILL",
        manifest_json=manifest,
        env_requirements={},
    )
    session.add(skill)
    await session.commit()
    return skill


async def _seed_install(session, *, user_id: str, skill_id: str):
    from app.models.user_skill_installation import UserSkillInstallation

    install = UserSkillInstallation(
        user_id=UUID(user_id),
        skill_id=skill_id,
        config_json={},
        granted_permissions=["network_read"],
        is_enabled=True,
    )
    session.add(install)
    await session.commit()
    return install


@pytest.mark.asyncio
async def test_plugin_market_lists_registry_projected_skills_for_regular_user(
    client,
    auth_tokens: dict,
    test_user: dict,
    AsyncSessionLocal,
) -> None:
    public_id = f"official.skills.monitor.{uuid4().hex}"
    admin_id = f"official.skills.database.{uuid4().hex}"

    async with AsyncSessionLocal() as session:
        await _seed_market_skill(session, skill_id=public_id, name="Public Skill")
        await _seed_market_skill(
            session,
            skill_id=admin_id,
            name="Admin Skill",
            restricted=True,
        )
        await _seed_install(session, user_id=test_user["id"], skill_id=public_id)

    resp = await client.get(
        "/api/v1/plugin-market/plugins",
        headers={"Authorization": f"Bearer {auth_tokens['access_token']}"},
    )
    assert resp.status_code == 200
    items = {item["id"]: item for item in resp.json()}
    assert items[public_id]["installed"] is True
    assert admin_id not in items


@pytest.mark.asyncio
async def test_plugin_market_lists_admin_projected_skills_for_superuser(
    client,
    admin_tokens: dict,
    AsyncSessionLocal,
) -> None:
    admin_id = f"official.skills.database.{uuid4().hex}"

    async with AsyncSessionLocal() as session:
        await _seed_market_skill(
            session,
            skill_id=admin_id,
            name="Admin Skill",
            restricted=True,
        )

    resp = await client.get(
        "/api/v1/plugin-market/plugins",
        headers={"Authorization": f"Bearer {admin_tokens['access_token']}"},
    )
    assert resp.status_code == 200
    items = {item["id"]: item for item in resp.json()}
    assert items[admin_id]["name"] == "Admin Skill"