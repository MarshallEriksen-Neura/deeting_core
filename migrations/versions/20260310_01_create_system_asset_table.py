"""create system asset table

Revision ID: 20260310_01_create_system_asset_table
Revises: 20260308_05_backfill_embedding_request_builder
Create Date: 2026-03-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260310_01_create_system_asset_table"
down_revision: str | None = "20260308_05_backfill_embedding_request_builder"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _json_type(dialect_name: str):
    return (
        postgresql.JSONB(astext_type=sa.Text())
        if dialect_name == "postgresql"
        else sa.JSON()
    )


def _json_default(dialect_name: str, value: str):
    suffix = "::jsonb" if dialect_name == "postgresql" else ""
    return sa.text(f"'{value}'{suffix}")


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("system_asset"):
        return

    dialect = bind.dialect.name if bind else "postgresql"
    json_type = _json_type(dialect)

    op.create_table(
        "system_asset",
        sa.Column("asset_id", sa.String(length=160), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("asset_kind", sa.String(length=20), server_default="capability", nullable=False),
        sa.Column("owner_scope", sa.String(length=20), server_default="system", nullable=False),
        sa.Column("source_kind", sa.String(length=20), server_default="official", nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False),
        sa.Column(
            "visibility_scope",
            sa.String(length=40),
            server_default="authenticated",
            nullable=False,
        ),
        sa.Column("local_sync_policy", sa.String(length=40), server_default="full", nullable=False),
        sa.Column("execution_policy", sa.String(length=40), server_default="allowed", nullable=False),
        sa.Column(
            "permission_grants",
            json_type,
            server_default=_json_default(dialect, "[]"),
            nullable=False,
        ),
        sa.Column(
            "allowed_role_names",
            json_type,
            server_default=_json_default(dialect, "[]"),
            nullable=False,
        ),
        sa.Column("artifact_ref", sa.String(length=1024), nullable=True),
        sa.Column("checksum", sa.String(length=255), nullable=True),
        sa.Column(
            "metadata_json",
            json_type,
            server_default=_json_default(dialect, "{}"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("asset_id", name=op.f("pk_system_asset")),
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("system_asset"):
        op.drop_table("system_asset")