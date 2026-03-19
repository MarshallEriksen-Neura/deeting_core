"""merge heads

Revision ID: 20260319_01_merge_heads
Revises: 20260313_01_add_desktop_oauth_intent, 20260316_01_drop_user_skill_installation
Create Date: 2026-03-19
"""

from __future__ import annotations

from typing import Sequence

revision: str = "20260319_01_merge_heads"
down_revision: str | Sequence[str] | None = (
    "20260313_01_add_desktop_oauth_intent",
    "20260316_01_drop_user_skill_installation",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
