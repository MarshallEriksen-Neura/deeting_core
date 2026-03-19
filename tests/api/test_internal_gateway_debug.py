import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.provider.config_driven_provider import ConfigDrivenProvider
from app.models.billing import BillingTransaction
from app.models.provider_instance import ProviderInstance, ProviderModel
from app.models.provider_preset import ProviderPreset
from app.repositories.quota_repository import QuotaRepository
from tests.utils.provider_protocol_profiles import build_protocol_profiles

DEFAULT_PROFILE_CONFIGS = {
    "chat": {
        "template_engine": "simple_replace",
        "request_template": {
            "model": None,
            "messages": None,
            "stream": None,
            "status_stream": None,
            "temperature": None,
            "max_tokens": None,
            "provider_model_id": None,
            "assistant_id": None,
            "session_id": None,
        },
        "response_transform": {},
        "default_headers": {},
        "default_params": {},
        "async_config": {},
    },
}

EMBEDDING_PROFILE_CONFIGS = {
    "embedding": {
        "template_engine": "simple_replace",
        "request_template": {
            "model": None,
            "input": None,
        },
        "response_transform": {},
        "default_headers": {},
        "default_params": {},
        "async_config": {},
    },
}


async def _seed_internal_provider(session) -> uuid.UUID:
    preset = ProviderPreset(
        id=uuid.uuid4(),
        name="OpenAI Debug",
        slug="openai-debug",
        provider="openai",
        base_url="https://api.openai.com",
        auth_type="bearer",
        auth_config={},
        protocol_schema_version="2026-03-07",
        protocol_profiles=build_protocol_profiles(
            provider="openai",
            profile_configs=DEFAULT_PROFILE_CONFIGS,
        ),
        is_active=True,
    )
    session.add(preset)

    instance = ProviderInstance(
        id=uuid.uuid4(),
        user_id=None,
        preset_slug="openai-debug",
        name="internal-openai",
        description="internal test instance",
        base_url="https://api.openai.com",
        icon=None,
        credentials_ref="ENV_TEST_KEY",
        priority=0,
        is_enabled=True,
        meta={},
    )
    session.add(instance)

    model = ProviderModel(
        id=uuid.uuid4(),
        instance_id=instance.id,
        capabilities=["chat"],  # 修复：使用 capabilities 复数形式，并且是数组
        model_id="gpt-4",
        unified_model_id=None,
        display_name="GPT-4",
        upstream_path="chat/completions",
        pricing_config={},
        limit_config={},
        tokenizer_config={},
        routing_config={},
        source="manual",
        extra_meta={},
        weight=100,
        priority=0,
        is_active=True,
    )
    session.add(model)
    await session.commit()
    return model.id


async def _seed_internal_embedding_provider(session) -> uuid.UUID:
    preset = ProviderPreset(
        id=uuid.uuid4(),
        name="OpenAI Embedding Debug",
        slug=f"openai-embedding-debug-{uuid.uuid4().hex[:8]}",
        provider="openai",
        base_url="https://api.openai.com",
        auth_type="bearer",
        auth_config={},
        protocol_schema_version="2026-03-07",
        protocol_profiles=build_protocol_profiles(
            provider="openai",
            profile_configs=EMBEDDING_PROFILE_CONFIGS,
        ),
        is_active=True,
    )
    session.add(preset)

    instance = ProviderInstance(
        id=uuid.uuid4(),
        user_id=None,
        preset_slug=preset.slug,
        name="internal-openai-embedding",
        description="internal embedding test instance",
        base_url="https://api.openai.com",
        icon=None,
        credentials_ref="ENV_TEST_KEY",
        priority=0,
        is_enabled=True,
        meta={},
    )
    session.add(instance)

    model = ProviderModel(
        id=uuid.uuid4(),
        instance_id=instance.id,
        capabilities=["embedding"],
        model_id="text-embedding-3-small",
        unified_model_id=None,
        display_name="text-embedding-3-small",
        upstream_path="embeddings",
        pricing_config={"input_per_1k": 0.5, "output_per_1k": 0.0},
        limit_config={},
        tokenizer_config={},
        routing_config={},
        source="manual",
        extra_meta={},
        weight=100,
        priority=0,
        is_active=True,
    )
    session.add(model)
    await session.commit()
    return model.id


@pytest.mark.asyncio
async def test_internal_step_registry(client, auth_tokens):
    resp = await client.get(
        "/api/v1/internal/debug/step-registry",
        headers={"Authorization": f"Bearer {auth_tokens['access_token']}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "steps" in data
    assert "routing" in data["steps"]


@pytest.mark.asyncio
async def test_internal_step_registry_requires_auth(client):
    resp = await client.get("/api/v1/internal/debug/step-registry")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_internal_test_routing(client, auth_tokens, AsyncSessionLocal):
    async with AsyncSessionLocal() as session:
        provider_model_id = await _seed_internal_provider(session)

    resp = await client.post(
        "/api/v1/internal/debug/test-routing",
        json={
            "model": "gpt-4",
            "capability": "chat",
            "provider_model_id": str(provider_model_id),
        },
        headers={"Authorization": f"Bearer {auth_tokens['access_token']}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["model"] == "gpt-4"
    assert data["capability"] == "chat"
    assert data["provider"] == "openai"
    assert data["upstream_url"].startswith("https://api.openai.com")


@pytest.mark.asyncio
async def test_internal_test_routing_validation_error(client, auth_tokens):
    resp = await client.post(
        "/api/v1/internal/debug/test-routing",
        json={"model": "", "capability": "chat"},
        headers={"Authorization": f"Bearer {auth_tokens['access_token']}"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_internal_test_routing_requires_provider_model_id(client, auth_tokens):
    resp = await client.post(
        "/api/v1/internal/debug/test-routing",
        json={"model": "gpt-4", "capability": "chat"},
        headers={"Authorization": f"Bearer {auth_tokens['access_token']}"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_internal_embeddings_route_executes_and_records_billing(
    client, auth_tokens, test_user, AsyncSessionLocal, monkeypatch
):
    async with AsyncSessionLocal() as session:
        provider_model_id = await _seed_internal_embedding_provider(session)
        quota_repo = QuotaRepository(session)
        quota = await quota_repo.get_or_create(test_user["id"])
        quota.balance = Decimal("20")
        await session.commit()

    async def fake_execute(self, request_payload, client, extra_context=None):
        assert request_payload["model"] == "text-embedding-3-small"
        assert request_payload["input"] == "hello embeddings"
        assert request_payload["provider_model_id"] == str(provider_model_id)
        return {
            "object": "list",
            "data": [{"object": "embedding", "index": 0, "embedding": [0.1, 0.2]}],
            "model": "text-embedding-3-small",
            "usage": {"prompt_tokens": 8, "total_tokens": 8},
        }

    monkeypatch.setattr(ConfigDrivenProvider, "execute", fake_execute)

    resp = await client.post(
        "/api/v1/internal/embeddings",
        json={
            "model": "text-embedding-3-small",
            "input": "hello embeddings",
            "provider_model_id": str(provider_model_id),
        },
        headers={"Authorization": f"Bearer {auth_tokens['access_token']}"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["data"][0]["embedding"] == [0.1, 0.2]
    assert data["model"] == "text-embedding-3-small"
    assert data["usage"]["prompt_tokens"] == 8
    assert "trace_id" in data

    async with AsyncSessionLocal() as session:
        tx = (
            await session.execute(
                select(BillingTransaction).where(
                    BillingTransaction.trace_id == data["trace_id"],
                )
            )
        ).scalar_one_or_none()

    assert tx is not None
    assert tx.provider_model_id == provider_model_id
    assert tx.input_tokens == 8
    assert tx.output_tokens == 0
    assert tx.amount > 0
