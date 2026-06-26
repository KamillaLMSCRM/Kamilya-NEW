"""add is_demo flag to tenants for prospect sandbox limits

The demo tenant (slug='demo') is a read-mostly sandbox used for
prospect trials. We need a cheap per-tenant flag so that limit
checks can be O(1) and central. Hiding this behind a JSONB
``settings`` query is possible but slower and harder to grep for.

The flag is also exposed via auth responses so the frontend can
render the sandbox banner.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column("is_demo", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    # Mark the legacy demo tenant so existing sandboxes stay sandbox.
    op.execute(
        "UPDATE tenants SET is_demo = true WHERE slug = 'demo'"
    )


def downgrade() -> None:
    op.drop_column("tenants", "is_demo")