from types import SimpleNamespace

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache_invalidation import CacheInvalidator
from app.core.database import get_db
from app.core.http_client import create_async_http_client
from app.core.logging import logger
from app.deps.superuser import get_current_superuser
from app.models.provider_preset import ProviderPreset
from app.protocols.canonical.models import CanonicalRequest
from app.protocols.runtime.profile_resolver import build_protocol_profile
from app.protocols.runtime.runtime_service import protocol_runtime_service
from app.protocols.runtime.transport_executor import execute_upstream_request
from app.repositories.provider_preset_repository import ProviderPresetRepository
from app.schemas.provider_preset import (
    ProviderPresetDTO,
    ProviderPresetDesktopUpsertRequest,
    ProviderPresetDesktopUpsertResponse,
    ProviderPresetPatchRequest,
    ProviderPresetVerifyRequest,
    ProviderPresetVerifyResponse,
    ProviderWish,
)
from app.tasks.search_index import upsert_provider_preset_task

router = APIRouter(prefix="/admin/provider-presets", tags=["ProviderPresets"])


@router.get("", response_model=list[ProviderPresetDTO])
async def list_presets(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_superuser),
):
    result = await db.execute(select(ProviderPreset).order_by(ProviderPreset.updated_at.desc()))
    return list(result.scalars().all())


@router.get("/{slug}", response_model=ProviderPresetDTO)
async def get_preset(
    slug: str,
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_superuser),
):
    repo = ProviderPresetRepository(db)
    preset = await repo.get_by_slug(slug)
    if preset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="provider_preset_not_found")
    return preset


@router.patch("/{slug}", response_model=ProviderPresetDTO)
async def patch_preset(
    slug: str,
    payload: ProviderPresetPatchRequest,
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_superuser),
):
    repo = ProviderPresetRepository(db)
    preset = await repo.get_by_slug(slug)
    if preset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="provider_preset_not_found")

    patch = payload.model_dump(exclude_unset=True)
    if "name" in patch and not str(patch["name"] or "").strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="name must not be empty")
    if "provider" in patch and not str(patch["provider"] or "").strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="provider must not be empty")
    if "base_url" in patch and not str(patch["base_url"] or "").strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="base_url must not be empty")

    normalized_profiles = None
    if "protocol_profiles" in patch:
        normalized_profiles = _normalize_protocol_profiles(
            provider=str(patch.get("provider") or preset.provider or "").strip(),
            protocol_profiles=patch.get("protocol_profiles"),
        )

    for field, value in patch.items():
        if field == "protocol_profiles":
            setattr(preset, field, normalized_profiles if normalized_profiles is not None else {})
            continue
        if field in {"name", "provider", "base_url"} and isinstance(value, str):
            value = value.strip()
        setattr(preset, field, value)

    db.add(preset)
    await db.commit()
    await db.refresh(preset)
    await CacheInvalidator().on_preset_updated(preset.slug)
    upsert_provider_preset_task.delay(preset.slug)
    return preset


@router.post("/{slug}/verify", response_model=ProviderPresetVerifyResponse)
async def verify_preset(
    slug: str,
    payload: ProviderPresetVerifyRequest,
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_superuser),
):
    repo = ProviderPresetRepository(db)
    preset = await repo.get_by_slug(slug)
    if preset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="provider_preset_not_found")

    draft = _build_preset_draft(preset, payload.preset_override)
    capability = str(payload.capability or "chat").strip().lower() or "chat"
    protocol_profiles = _normalize_protocol_profiles(
        provider=str(draft.provider or "").strip(),
        protocol_profiles=getattr(draft, "protocol_profiles", {}),
    )
    raw_profile = protocol_profiles.get(capability)
    if not isinstance(raw_profile, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"provider_preset_capability_missing:{capability}",
        )

    canonical_request = _build_skeleton_request(
        capability=capability,
        model=payload.model,
        prompt=payload.prompt,
        temperature=payload.temperature,
        max_output_tokens=payload.max_output_tokens,
    )
    upstream_request = protocol_runtime_service.build_upstream_request(
        canonical_request,
        raw_profile,
        base_url=str(draft.base_url or "").strip(),
    )
    upstream_request.headers = _inject_temp_auth(
        headers=upstream_request.headers,
        auth_type=str(draft.auth_type or "api_key").strip(),
        auth_config=getattr(draft, "auth_config", {}) or {},
        api_key=payload.api_key,
    )

    async with create_async_http_client(timeout=15.0) as http_client:
        response = await execute_upstream_request(upstream_request, client=http_client)

    return ProviderPresetVerifyResponse(
        status="success" if response.is_success else "error",
        status_code=response.status_code,
        capability=capability,
        rendered_request={
            "method": upstream_request.method,
            "url": upstream_request.url,
            "headers": upstream_request.headers,
            "query": upstream_request.query,
            "body": upstream_request.body,
        },
        response_preview=response.text[:1000],
    )


@router.post("/wishes", status_code=status.HTTP_202_ACCEPTED)
async def wish_provider(
    payload: ProviderWish,
    user=Depends(get_current_superuser),
):
    """
    Submit a wish for a new provider.
    Currently just logs the wish, but can be extended to store in DB.
    """
    logger.info(
        "provider_wish_submitted",
        extra={
            "user_id": str(user.id),
            "provider_name": payload.provider_name,
            "url": payload.url,
            "description": payload.description,
        },
    )
    return {"message": "Wish received"}


@router.post("/upsert-from-desktop", response_model=ProviderPresetDesktopUpsertResponse)
async def upsert_provider_preset_from_desktop(
    payload: ProviderPresetDesktopUpsertRequest,
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_superuser),
):
    preset_payload = payload.preset.model_dump()
    slug = str(preset_payload.get("slug") or "").strip()
    name = str(preset_payload.get("name") or "").strip()
    provider = str(preset_payload.get("provider") or "").strip()
    base_url = str(preset_payload.get("base_url") or "").strip()

    if not slug or not name or not provider or not base_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="slug, name, provider, and base_url are required",
        )

    repo = ProviderPresetRepository(db)
    existing = await repo.get_by_slug(slug)
    normalized_payload = {
        "slug": slug,
        "name": name,
        "provider": provider,
        "category": preset_payload.get("category"),
        "base_url": base_url,
        "url_template": preset_payload.get("url_template"),
        "theme_color": preset_payload.get("theme_color"),
        "icon": preset_payload.get("icon") or "lucide:cpu",
        "auth_type": preset_payload.get("auth_type") or "api_key",
        "auth_config": preset_payload.get("auth_config") or {},
        "protocol_schema_version": preset_payload.get("protocol_schema_version"),
        "protocol_profiles": _normalize_protocol_profiles(
            provider=provider,
            protocol_profiles=preset_payload.get("protocol_profiles") or {},
        ),
        "version": int(preset_payload.get("version") or 1),
        "is_active": bool(preset_payload.get("is_active", True)),
    }

    if existing is None:
        db.add(ProviderPreset(**normalized_payload))
        updated = False
    else:
        updated = True
        for key, value in normalized_payload.items():
            setattr(existing, key, value)
        db.add(existing)

    await db.commit()
    await CacheInvalidator().on_preset_updated(slug)
    upsert_provider_preset_task.delay(slug)

    return ProviderPresetDesktopUpsertResponse(
        status="ok",
        slug=slug,
        updated=updated,
    )


def _build_preset_draft(
    preset: ProviderPreset,
    override: ProviderPresetPatchRequest | None,
) -> SimpleNamespace:
    draft = {
        "slug": preset.slug,
        "name": preset.name,
        "provider": preset.provider,
        "category": preset.category,
        "base_url": preset.base_url,
        "url_template": preset.url_template,
        "theme_color": preset.theme_color,
        "icon": preset.icon,
        "auth_type": preset.auth_type,
        "auth_config": preset.auth_config or {},
        "protocol_schema_version": preset.protocol_schema_version,
        "protocol_profiles": preset.protocol_profiles or {},
        "version": preset.version,
        "is_active": preset.is_active,
    }
    if override is not None:
        for key, value in override.model_dump(exclude_unset=True).items():
            draft[key] = value
    if "protocol_profiles" in draft:
        draft["protocol_profiles"] = _normalize_protocol_profiles(
            provider=str(draft.get("provider") or "").strip(),
            protocol_profiles=draft.get("protocol_profiles"),
        )
    return SimpleNamespace(**draft)


def _normalize_protocol_profiles(
    *,
    provider: str,
    protocol_profiles: dict | None,
) -> dict:
    if protocol_profiles is None:
        return {}
    if not isinstance(protocol_profiles, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="protocol_profiles must be an object",
        )
    normalized: dict[str, dict] = {}
    for capability, raw_profile in protocol_profiles.items():
        if not isinstance(raw_profile, dict):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"protocol_profiles.{capability} must be an object",
            )
        normalized[str(capability)] = _normalize_protocol_profile(
            provider=provider,
            capability=str(capability),
            raw_profile=raw_profile,
        )
    return normalized


def _normalize_protocol_profile(
    *,
    provider: str,
    capability: str,
    raw_profile: dict,
) -> dict:
    request = raw_profile.get("request") if isinstance(raw_profile.get("request"), dict) else {}
    transport = raw_profile.get("transport") if isinstance(raw_profile.get("transport"), dict) else {}
    response = raw_profile.get("response") if isinstance(raw_profile.get("response"), dict) else {}
    defaults = raw_profile.get("defaults") if isinstance(raw_profile.get("defaults"), dict) else {}
    metadata = raw_profile.get("metadata") if isinstance(raw_profile.get("metadata"), dict) else {}

    protocol_family = str(
        raw_profile.get("protocol_family")
        or metadata.get("protocol_family")
        or provider
    ).strip()
    upstream_path = str(
        raw_profile.get("upstream_path")
        or transport.get("path")
        or ""
    ).strip()
    template_engine = str(
        raw_profile.get("template_engine")
        or request.get("template_engine")
        or ""
    ).strip()
    request_template = (
        raw_profile.get("request_template")
        or request.get("request_template")
        or {}
    )
    response_transform = (
        raw_profile.get("response_transform")
        or response.get("response_template")
        or {}
    )
    output_mapping = (
        raw_profile.get("output_mapping")
        or response.get("output_mapping")
        or {}
    )
    request_builder = _coerce_runtime_hook(
        raw_profile.get("request_builder") or request.get("request_builder")
    )
    default_headers = (
        raw_profile.get("default_headers")
        or defaults.get("headers")
        or {}
    )
    default_params = (
        raw_profile.get("default_params")
        or defaults.get("body")
        or {}
    )
    async_config = metadata.get("async_config") if isinstance(metadata.get("async_config"), dict) else {}
    protocol_profile = build_protocol_profile(
        provider=provider,
        capability=capability,
        protocol=protocol_family or provider,
        upstream_path=upstream_path or _default_upstream_path(capability, protocol_family),
        http_method=str(
            raw_profile.get("http_method")
            or raw_profile.get("method")
            or transport.get("method")
            or ""
        ).strip(),
        template_engine=template_engine,
        request_template=request_template if isinstance(request_template, (dict, str)) else {},
        response_transform=response_transform if isinstance(response_transform, dict) else {},
        output_mapping=output_mapping if isinstance(output_mapping, dict) else {},
        request_builder=request_builder,
        default_headers=default_headers if isinstance(default_headers, dict) else {},
        default_params=default_params if isinstance(default_params, dict) else {},
        async_config=async_config,
    )
    return protocol_profile.model_dump(mode="python")


def _coerce_runtime_hook(value):
    if isinstance(value, str) and value.strip():
        return {"name": value.strip(), "config": {}}
    if isinstance(value, dict):
        name = str(value.get("name") or "").strip()
        if name:
            config = value.get("config")
            return {
                "name": name,
                "config": config if isinstance(config, dict) else {},
            }
    return None


def _default_upstream_path(capability: str, protocol_family: str) -> str:
    if capability == "embedding":
        return "embeddings"
    if capability == "image_generation":
        return "images/generations"
    if capability == "video_generation":
        return "videos/generations"
    if capability == "text_to_speech":
        return "audio/speech"
    if capability == "speech_to_text":
        return "audio/transcriptions"
    if protocol_family == "openai_responses":
        return "responses"
    if protocol_family == "anthropic_messages":
        return "messages"
    return "chat/completions"


def _build_skeleton_request(
    *,
    capability: str,
    model: str,
    prompt: str,
    temperature: float | None,
    max_output_tokens: int | None,
) -> CanonicalRequest:
    normalized_prompt = str(prompt or "ping").strip() or "ping"
    if capability == "embedding":
        return CanonicalRequest(
            capability="embedding",
            model=model,
            input_items=[{"type": "text", "text": normalized_prompt}],
        )
    if capability == "image_generation":
        return CanonicalRequest(
            capability="image_generation",
            model=model,
            input_items=[{"type": "text", "text": normalized_prompt}],
        )
    return CanonicalRequest(
        capability="chat",
        model=model,
        messages=[{"role": "user", "content": normalized_prompt}],
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        stream=False,
    )


def _inject_temp_auth(
    *,
    headers: dict,
    auth_type: str,
    auth_config: dict,
    api_key: str,
) -> dict:
    resolved_headers = dict(headers or {})
    normalized_auth_type = (auth_type or "api_key").strip().lower()
    if normalized_auth_type == "none":
        return resolved_headers
    if normalized_auth_type == "bearer":
        resolved_headers["Authorization"] = f"Bearer {api_key}"
        return resolved_headers
    header_name = str((auth_config or {}).get("header") or "x-api-key").strip() or "x-api-key"
    resolved_headers[header_name] = api_key
    return resolved_headers
