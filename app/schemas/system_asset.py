from __future__ import annotations

from pydantic import Field

from app.schemas.base import BaseSchema


class SystemAssetPolicySnapshot(BaseSchema):
    visibility_scope: str
    local_sync_policy: str
    execution_policy: str
    permission_grants: list[str] = Field(default_factory=list)
    allowed_role_names: list[str] = Field(default_factory=list)
    materialization_state: str


class SystemAssetSyncItem(BaseSchema):
    asset_id: str
    title: str
    description: str | None = None
    asset_kind: str
    owner_scope: str
    source_kind: str
    version: str
    artifact_ref: str | None = None
    checksum: str | None = None
    metadata_json: dict = Field(default_factory=dict)
    policy_snapshot: SystemAssetPolicySnapshot


class SystemAssetSyncResponse(BaseSchema):
    items: list[SystemAssetSyncItem] = Field(default_factory=list)
