"""create desktop browser login session tables

Revision ID: 20260319_02_desktop_browser_login_session
Revises: 20260319_01_merge_heads
Create Date: 2026-03-19
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260319_02_desktop_browser_login_session"
down_revision: str | Sequence[str] | None = "20260319_01_merge_heads"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "desktop_browser_login_session",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("redirect_scheme", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_account.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("client_fingerprint", sa.String(255), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_desktop_browser_login_session_status",
        "desktop_browser_login_session",
        ["status"],
    )
    op.create_index(
        "ix_desktop_browser_login_session_user_id",
        "desktop_browser_login_session",
        ["user_id"],
    )
    op.create_index(
        "ix_desktop_browser_login_session_expires_at",
        "desktop_browser_login_session",
        ["expires_at"],
    )

    op.create_table(
        "desktop_browser_login_grant",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("desktop_browser_login_session.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("grant_hash", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_desktop_browser_login_grant_session_id",
        "desktop_browser_login_grant",
        ["session_id"],
    )
    op.create_index(
        "ix_desktop_browser_login_grant_grant_hash",
        "desktop_browser_login_grant",
        ["grant_hash"],
        unique=True,
    )
    op.create_index(
        "ix_desktop_browser_login_grant_status",
        "desktop_browser_login_grant",
        ["status"],
    )
    op.create_index(
        "ix_desktop_browser_login_grant_expires_at",
        "desktop_browser_login_grant",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_desktop_browser_login_grant_expires_at",
        table_name="desktop_browser_login_grant",
    )
    op.drop_index(
        "ix_desktop_browser_login_grant_status",
        table_name="desktop_browser_login_grant",
    )
    op.drop_index(
        "ix_desktop_browser_login_grant_grant_hash",
        table_name="desktop_browser_login_grant",
    )
    op.drop_index(
        "ix_desktop_browser_login_grant_session_id",
        table_name="desktop_browser_login_grant",
    )
    op.drop_table("desktop_browser_login_grant")

    op.drop_index(
        "ix_desktop_browser_login_session_expires_at",
        table_name="desktop_browser_login_session",
    )
    op.drop_index(
        "ix_desktop_browser_login_session_user_id",
        table_name="desktop_browser_login_session",
    )
    op.drop_index(
        "ix_desktop_browser_login_session_status",
        table_name="desktop_browser_login_session",
    )
    op.drop_table("desktop_browser_login_session")
