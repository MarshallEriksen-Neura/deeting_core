"""seed web scout and skill learner assistant (removed)

This migration previously seeded a Scout assistant and crawler skill entry.
The Scout project has been removed; this migration is now a no-op.

Revision ID: seed_web_scout_assistant
Revises: 20260214_01_fix_modelscope_image_generation_template
Create Date: 2026-02-22
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "seed_web_scout_assistant"
down_revision = "20260214_01_fix_modelscope_image_generation_template"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
