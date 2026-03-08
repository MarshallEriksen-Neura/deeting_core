"""backfill embedding request builder in provider preset protocol profiles

Revision ID: 20260308_05_backfill_embedding_request_builder
Revises: 20260308_04_seed_nvidia_provider_preset
Create Date: 2026-03-08
"""

from __future__ import annotations

import copy
from typing import Any, Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260308_05_backfill_embedding_request_builder"
down_revision: str | Sequence[str] | None = "20260308_04_seed_nvidia_provider_preset"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OPENAI_EMBEDDING_BUILDER = {
    "name": "embedding_request_from_input_items",
    "config": {"mode": "openai"},
}
_GEMINI_EMBEDDING_BUILDER = {
    "name": "embedding_request_from_input_items",
    "config": {"mode": "gemini"},
}


def _is_gemini_like_provider(provider: str | None) -> bool:
    provider_lower = str(provider or "").strip().lower()
    return (
        "gemini" in provider_lower
        or "google" in provider_lower
        or "vertex" in provider_lower
    )


def _builder_for_provider(provider: str | None) -> dict[str, Any]:
    if _is_gemini_like_provider(provider):
        return copy.deepcopy(_GEMINI_EMBEDDING_BUILDER)
    return copy.deepcopy(_OPENAI_EMBEDDING_BUILDER)


def _patch_protocol_profiles(
    provider: str | None,
    protocol_profiles: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, bool]:
    if not isinstance(protocol_profiles, dict):
        return protocol_profiles, False

    embedding_profile = protocol_profiles.get("embedding")
    if not isinstance(embedding_profile, dict):
        return protocol_profiles, False

    request_config = embedding_profile.get("request")
    if not isinstance(request_config, dict):
        return protocol_profiles, False

    if request_config.get("request_builder") is not None:
        return protocol_profiles, False

    updated = copy.deepcopy(protocol_profiles)
    updated["embedding"]["request"]["request_builder"] = _builder_for_provider(provider)
    return updated, True


def _revert_protocol_profiles(
    provider: str | None,
    protocol_profiles: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, bool]:
    if not isinstance(protocol_profiles, dict):
        return protocol_profiles, False

    embedding_profile = protocol_profiles.get("embedding")
    if not isinstance(embedding_profile, dict):
        return protocol_profiles, False

    request_config = embedding_profile.get("request")
    if not isinstance(request_config, dict):
        return protocol_profiles, False

    expected_builder = _builder_for_provider(provider)
    if request_config.get("request_builder") != expected_builder:
        return protocol_profiles, False

    updated = copy.deepcopy(protocol_profiles)
    updated["embedding"]["request"]["request_builder"] = None
    return updated, True


def upgrade() -> None:
    conn = op.get_bind()
    provider_preset = sa.table(
        "provider_preset",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("provider", sa.String()),
        sa.column("protocol_profiles", postgresql.JSONB),
    )

    rows = conn.execute(
        sa.select(
            provider_preset.c.id,
            provider_preset.c.provider,
            provider_preset.c.protocol_profiles,
        )
    ).fetchall()

    for row in rows:
        updated_profiles, changed = _patch_protocol_profiles(
            row.provider,
            row.protocol_profiles,
        )
        if not changed:
            continue
        conn.execute(
            provider_preset.update()
            .where(provider_preset.c.id == row.id)
            .values(protocol_profiles=updated_profiles)
        )


def downgrade() -> None:
    conn = op.get_bind()
    provider_preset = sa.table(
        "provider_preset",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("provider", sa.String()),
        sa.column("protocol_profiles", postgresql.JSONB),
    )

    rows = conn.execute(
        sa.select(
            provider_preset.c.id,
            provider_preset.c.provider,
            provider_preset.c.protocol_profiles,
        )
    ).fetchall()

    for row in rows:
        updated_profiles, changed = _revert_protocol_profiles(
            row.provider,
            row.protocol_profiles,
        )
        if not changed:
            continue
        conn.execute(
            provider_preset.update()
            .where(provider_preset.c.id == row.id)
            .values(protocol_profiles=updated_profiles)
        )
