"""make tenant_id nullable on users (superadmin doesn't belong to tenant)

A platform operator (superadmin) is not scoped to a single tenant;
their ``users.tenant_id`` is NULL. We keep the column for tenant
users and add a partial unique index that treats NULLs as distinct
(already the case via the existing ``uq_user_telegram`` partial index).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("users", "tenant_id", existing_type=sa.UUID(), nullable=True)


def downgrade() -> None:
    # Refuse to downgrade if any superadmin rows exist (would violate NOT NULL).
    op.execute("DELETE FROM users WHERE tenant_id IS NULL AND role = 'superadmin'")
    op.alter_column("users", "tenant_id", existing_type=sa.UUID(), nullable=False)