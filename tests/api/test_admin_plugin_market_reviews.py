from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select

from app.models.skill_registry import SkillRegistry


def _build_manifest(summary: str = "Needs admin approval") -> dict[str, Any]:
    return {
        "name": "HTTP Fetch",
        "summary": summary,
        "permissions": ["network.outbound", "files.read"],
        "execution": {"timeout_seconds": 60},
        "deeting_ingestion": {
            "requires_admin_approval": True,
            "submission_channel": "plugin_market",
            "submitter_user_id": "00000000-0000-0000-0000-000000000010",
            "security_review": {
                "decision": "needs_review",
                "summary": summary,
                "network_targets": ["api.example.com"],
                "destructive_actions": ["writes files"],
                "privacy_risks": ["may access user data"],
                "findings": [
                    {
                        "severity": "medium",
                        "category": "network",
                        "message": "Calls external API",
                        "file": "skill.py",
                    }
                ],
            },
        },
    }


async def _seed_skill(AsyncSessionLocal, skill_id: str, status: str = "needs_review") -> None:
    async with AsyncSessionLocal() as session:
        session.add(
            SkillRegistry(
                id=skill_id,
                name="HTTP Fetch",
                version="1.0.0",
                runtime="python",
                description="Fetches remote data",
                source_repo="https://github.com/example/http-fetch",
                source_revision="abc123",
                risk_level="high",
                status=status,
                manifest_json=_build_manifest(),
                env_requirements={"python": ">=3.11"},
            )
        )
        await session.commit()


async def _get_skill(AsyncSessionLocal, skill_id: str) -> SkillRegistry:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(SkillRegistry).where(SkillRegistry.id == skill_id)
        )
        skill = result.scalar_one()
        session.expunge(skill)
        return skill


@pytest.mark.asyncio
async def test_list_plugin_market_reviews(client, admin_tokens: dict, AsyncSessionLocal):
    await _seed_skill(AsyncSessionLocal, "market.review.list")
    headers = {"Authorization": f"Bearer {admin_tokens['access_token']}"}

    response = await client.get(
        "/api/v1/admin/plugin-reviews",
        headers=headers,
        params={"status_filter": "needs_review"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["total"] >= 1
    item = next(row for row in payload["items"] if row["id"] == "market.review.list")
    assert item["submitter_user_id"] == "00000000-0000-0000-0000-000000000010"
    assert item["security_review_summary"] == "Needs admin approval"
    assert item["security_review_decision"] == "needs_review"
    assert item["findings"][0]["category"] == "network"
    assert item["manifest_json"]["permissions"] == ["network.outbound", "files.read"]


@pytest.mark.asyncio
async def test_approve_plugin_market_review(client, admin_tokens: dict, AsyncSessionLocal):
    await _seed_skill(AsyncSessionLocal, "market.review.approve")
    headers = {"Authorization": f"Bearer {admin_tokens['access_token']}"}

    response = await client.post(
        "/api/v1/admin/plugin-reviews/market.review.approve/approve",
        headers=headers,
        json={"reason": "looks safe"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "active"
    assert payload["review_reason"] == "looks safe"

    skill = await _get_skill(AsyncSessionLocal, "market.review.approve")
    assert skill.status == "active"
    assert skill.manifest_json["deeting_ingestion"]["admin_review"]["decision"] == "approved"
    assert skill.manifest_json["deeting_ingestion"]["admin_review"]["reason"] == "looks safe"


@pytest.mark.asyncio
async def test_reject_plugin_market_review(client, admin_tokens: dict, AsyncSessionLocal):
    await _seed_skill(AsyncSessionLocal, "market.review.reject")
    headers = {"Authorization": f"Bearer {admin_tokens['access_token']}"}

    response = await client.post(
        "/api/v1/admin/plugin-reviews/market.review.reject/reject",
        headers=headers,
        json={"reason": "uses unsafe operations"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "rejected"
    assert payload["review_reason"] == "uses unsafe operations"

    skill = await _get_skill(AsyncSessionLocal, "market.review.reject")
    assert skill.status == "rejected"
    assert skill.manifest_json["deeting_ingestion"]["admin_review"]["decision"] == "rejected"

