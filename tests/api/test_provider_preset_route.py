from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select

from app.models import ProviderPreset
from app.protocols.runtime.transport_executor import UpstreamRequest
from tests.utils.provider_protocol_profiles import build_protocol_profiles


@pytest.mark.asyncio
async def test_admin_provider_presets_exposes_full_sync_fields(
    client, admin_tokens, AsyncSessionLocal
):
    slug = f"desktop-sync-{uuid4().hex[:8]}"
    async with AsyncSessionLocal() as session:
        session.add(
            ProviderPreset(
                name="Desktop Sync Provider",
                slug=slug,
                provider="custom",
                category="Cloud API",
                base_url="https://api.example.com",
                url_template="https://{resource}.example.com",
                auth_type="api_key",
                auth_config={"header": "x-api-key"},
                protocol_schema_version="2026-03-07",
                protocol_profiles=build_protocol_profiles(
                    provider="custom",
                    default_headers={"X-Test": "1"},
                    default_params={"temperature": 0.2},
                    profile_configs={
                        "chat": {
                            "template_engine": "simple_replace",
                            "request_template": {"model": None, "messages": None},
                            "response_transform": {
                                "content_path": "choices.0.message.content"
                            },
                        }
                    },
                ),
                theme_color="#123456",
                version=3,
                is_active=True,
            )
        )
        await session.commit()

    headers = {"Authorization": f"Bearer {admin_tokens['access_token']}"}
    response = await client.get("/api/v1/admin/provider-presets", headers=headers)
    assert response.status_code == 200

    item = next(p for p in response.json() if p["slug"] == slug)
    assert item["auth_type"] == "api_key"
    assert item["auth_config"]["header"] == "x-api-key"
    assert item["protocol_schema_version"] == "2026-03-07"
    assert item["protocol_profiles"]["chat"]["protocol_family"] == "openai_chat"
    assert item["version"] == 3


@pytest.mark.asyncio
async def test_admin_provider_preset_detail_returns_editable_fields(
    client, admin_tokens, AsyncSessionLocal
):
    slug = f"provider-detail-{uuid4().hex[:8]}"
    async with AsyncSessionLocal() as session:
        session.add(
            ProviderPreset(
                name="Provider Detail",
                slug=slug,
                provider="custom",
                category="Cloud API",
                base_url="https://detail.example.com",
                url_template="https://detail.example.com/docs",
                auth_type="bearer",
                auth_config={"header": "authorization"},
                protocol_schema_version="2026-03-07",
                protocol_profiles={
                    "chat": {
                        "protocol_family": "openai_chat",
                        "transport": {"path": "chat/completions"},
                        "request": {
                            "template_engine": "openai_compat",
                            "request_template": {"model": None, "messages": None},
                        },
                    }
                },
                theme_color="#abcdef",
                icon="lucide:cpu",
                version=2,
                is_active=True,
            )
        )
        await session.commit()

    headers = {"Authorization": f"Bearer {admin_tokens['access_token']}"}
    response = await client.get(f"/api/v1/admin/provider-presets/{slug}", headers=headers)
    assert response.status_code == 200

    body = response.json()
    assert body["slug"] == slug
    assert body["auth_config"]["header"] == "authorization"
    assert body["protocol_profiles"]["chat"]["protocol_family"] == "openai_chat"
    assert body["version"] == 2


@pytest.mark.asyncio
async def test_admin_provider_preset_patch_preserves_existing_object_fields_when_omitted(
    client, admin_tokens, AsyncSessionLocal
):
    slug = f"provider-patch-{uuid4().hex[:8]}"
    original_profiles = {
        "chat": {
            "protocol_family": "openai_chat",
            "transport": {"path": "chat/completions"},
            "request": {
                "template_engine": "openai_compat",
                "request_template": {"model": None, "messages": None},
            },
        }
    }
    async with AsyncSessionLocal() as session:
        session.add(
            ProviderPreset(
                name="Patch Me",
                slug=slug,
                provider="custom",
                category="Cloud API",
                base_url="https://patch.example.com",
                auth_type="bearer",
                auth_config={"header": "authorization"},
                protocol_schema_version="2026-03-07",
                protocol_profiles=original_profiles,
                icon="lucide:cpu",
                version=1,
                is_active=True,
            )
        )
        await session.commit()

    headers = {"Authorization": f"Bearer {admin_tokens['access_token']}"}
    response = await client.patch(
        f"/api/v1/admin/provider-presets/{slug}",
        headers=headers,
        json={
            "name": "Patched Name",
            "base_url": "https://patched.example.com",
        },
    )
    assert response.status_code == 200

    async with AsyncSessionLocal() as session:
        refreshed = (
            await session.execute(
                select(ProviderPreset).where(ProviderPreset.slug == slug)
            )
        ).scalars().first()

    assert refreshed is not None
    assert refreshed.name == "Patched Name"
    assert refreshed.base_url == "https://patched.example.com"
    assert refreshed.auth_config == {"header": "authorization"}
    assert refreshed.protocol_profiles == original_profiles


@pytest.mark.asyncio
async def test_admin_provider_preset_verify_renders_skeleton_request_with_temp_api_key(
    client, admin_tokens, AsyncSessionLocal, monkeypatch: pytest.MonkeyPatch
):
    slug = f"provider-verify-{uuid4().hex[:8]}"
    async with AsyncSessionLocal() as session:
        session.add(
            ProviderPreset(
                name="Verify Me",
                slug=slug,
                provider="custom",
                category="Cloud API",
                base_url="https://verify.example.com/v1",
                auth_type="bearer",
                auth_config={},
                protocol_schema_version="2026-03-07",
                protocol_profiles=build_protocol_profiles(
                    provider="custom",
                    profile_configs={
                        "chat": {
                            "template_engine": "openai_compat",
                            "request_template": {"model": None, "messages": None},
                        }
                    },
                ),
                icon="lucide:cpu",
                version=1,
                is_active=True,
            )
        )
        await session.commit()

    captured: dict[str, object] = {}

    async def _fake_execute(
        upstream_request: UpstreamRequest,
        client: httpx.AsyncClient | None = None,
    ) -> httpx.Response:
        captured["request"] = upstream_request
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "pong"}}]},
        )

    monkeypatch.setattr(
        "app.api.v1.admin.provider_preset_route.execute_upstream_request",
        _fake_execute,
    )

    headers = {"Authorization": f"Bearer {admin_tokens['access_token']}"}
    response = await client.post(
        f"/api/v1/admin/provider-presets/{slug}/verify",
        headers=headers,
        json={
            "capability": "chat",
            "api_key": "test-secret",
            "model": "doubao-1-5-lite-32k-250115",
            "prompt": "ping",
        },
    )
    assert response.status_code == 200

    body = response.json()
    assert body["status"] == "success"
    assert body["status_code"] == 200
    assert "pong" in body["response_preview"]

    upstream_request = captured["request"]
    assert isinstance(upstream_request, UpstreamRequest)
    assert upstream_request.url == "https://verify.example.com/v1/chat/completions"
    assert upstream_request.headers["Authorization"] == "Bearer test-secret"
    assert upstream_request.body["model"] == "doubao-1-5-lite-32k-250115"
    assert upstream_request.body["messages"][0]["content"] == "ping"
