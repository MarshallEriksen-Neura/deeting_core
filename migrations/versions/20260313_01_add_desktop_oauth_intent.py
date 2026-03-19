"""add desktop oauth session intent

Revision ID: 20260313_01_add_desktop_oauth_intent
Revises: 20260310_01_create_system_asset_table
Create Date: 2026-03-13
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260313_01_add_desktop_oauth_intent"
down_revision: str | Sequence[str] | None = "20260310_01_create_system_asset_table"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "desktop_oauth_session",
        sa.Column(
            "intent",
            sa.String(length=32),
            nullable=False,
            server_default="login",
        ),
    )
    op.create_index(
        "ix_desktop_oauth_session_intent",
        "desktop_oauth_session",
        ["intent"],
    )
    op.alter_column("desktop_oauth_session", "intent", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_desktop_oauth_session_intent", table_name="desktop_oauth_session")
    op.drop_column("desktop_oauth_session", "intent")
