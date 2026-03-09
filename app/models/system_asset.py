from __future__ import annotations

from typing import Any

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin
from app.models.provider_preset import JSONBCompat


class SystemAsset(Base, TimestampMixin):
    __tablename__ = "system_asset"

    asset_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    asset_kind: Mapped[str] = mapped_column(
        String(20), nullable=False, default="capability", server_default="capability"
    )
    owner_scope: Mapped[str] = mapped_column(
        String(20), nullable=False, default="system", server_default="system"
    )
    source_kind: Mapped[str] = mapped_column(
        String(20), nullable=False, default="official", server_default="official"
    )
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", server_default="active"
    )
    visibility_scope: Mapped[str] = mapped_column(
        String(40), nullable=False, default="authenticated", server_default="authenticated"
    )
    local_sync_policy: Mapped[str] = mapped_column(
        String(40), nullable=False, default="full", server_default="full"
    )
    execution_policy: Mapped[str] = mapped_column(
        String(40), nullable=False, default="allowed", server_default="allowed"
    )
    permission_grants: Mapped[list[str]] = mapped_column(
        JSONBCompat, nullable=False, default=list, server_default="[]"
    )
    allowed_role_names: Mapped[list[str]] = mapped_column(
        JSONBCompat, nullable=False, default=list, server_default="[]"
    )
    artifact_ref: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    checksum: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSONBCompat, nullable=False, default=dict, server_default="{}"
    )

    def __init__(self, **kwargs: Any) -> None:
        if kwargs.get("permission_grants") is None:
            kwargs["permission_grants"] = []
        if kwargs.get("allowed_role_names") is None:
            kwargs["allowed_role_names"] = []
        if kwargs.get("metadata_json") is None:
            kwargs["metadata_json"] = {}
        super().__init__(**kwargs)
