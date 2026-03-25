"""Provider preset DTOs for admin APIs."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseSchema


class ProviderPresetDTO(BaseSchema):
    id: UUID | None = None
    slug: str | None = None
    name: str | None = None
    provider: str | None = None
    category: str | None = None
    base_url: str | None = None
    url_template: str | None = None
    theme_color: str | None = None
    icon: str | None = None
    auth_type: str | None = None
    auth_config: dict[str, Any] = Field(default_factory=dict)
    protocol_schema_version: str | None = None
    protocol_profiles: dict[str, Any] = Field(default_factory=dict)
    version: int = 1
    is_active: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None


ProviderPresetBase = ProviderPresetDTO
ProviderPresetCreate = ProviderPresetDTO
ProviderPresetUpdate = ProviderPresetDTO


class ProviderPresetPatchRequest(BaseSchema):
    name: str | None = None
    provider: str | None = None
    category: str | None = None
    base_url: str | None = None
    url_template: str | None = None
    theme_color: str | None = None
    icon: str | None = None
    auth_type: str | None = None
    auth_config: dict[str, Any] | None = None
    protocol_schema_version: str | None = None
    protocol_profiles: dict[str, Any] | None = None
    version: int | None = None
    is_active: bool | None = None


class ProviderPresetCreateRequest(BaseSchema):
    slug: str
    name: str
    provider: str
    base_url: str
    category: str | None = None
    url_template: str | None = None
    theme_color: str | None = None
    icon: str | None = None
    auth_type: str | None = None
    auth_config: dict[str, Any] = Field(default_factory=dict)
    protocol_schema_version: str | None = None
    protocol_profiles: dict[str, Any] = Field(default_factory=dict)
    version: int = 1
    is_active: bool = True


class ProviderPresetDeleteResponse(BaseSchema):
    status: str
    slug: str


class ProviderPresetVerifyRequest(BaseSchema):
    capability: str = "chat"
    api_key: str
    model: str
    prompt: str = "ping"
    temperature: float | None = None
    max_output_tokens: int | None = 32
    preset_override: ProviderPresetPatchRequest | None = None


class ProviderPresetVerifyResponse(BaseSchema):
    status: str
    status_code: int
    capability: str
    rendered_request: dict[str, Any] = Field(default_factory=dict)
    response_preview: str = ""


class ProviderWish(BaseSchema):
    provider_name: str
    description: str | None = None
    url: str | None = None


class ProviderPresetDesktopUpsertRequest(BaseSchema):
    preset: ProviderPresetDTO


class ProviderPresetDesktopUpsertResponse(BaseSchema):
    status: str
    slug: str
    updated: bool
