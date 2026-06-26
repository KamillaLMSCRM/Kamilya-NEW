"""add tenant subscription fields for superadmin management

Adds columns to `tenants` so the superadmin UI can manage plans,
trial windows, and per-tenant limits without a separate billing table
(v1.0 — full billing integration is a separate epic).

New columns:
- trial_ends_at      DateTime  — end of trial period (informational)
- paid_until         DateTime  — paid plan renews at this date
- max_users          Integer   — seat cap (NULL = unlimited)
- max_courses_per_month Integer — generation cap (NULL = unlimited)
- notes              Text      — superadmin-only notes (not shown to tenant)

The existing `plan` (text) and `status` (text) columns stay — we keep
them free-form so future plan names don't need a migration. The
superadmin UI enforces the whitelist client-side and the API schema
validates the values server-side.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column("trial_ends_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "tenants",
        sa.Column("paid_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "tenants",
        sa.Column("max_users", sa.Integer, nullable=True),
    )
    op.add_column(
        "tenants",
        sa.Column("max_courses_per_month", sa.Integer, nullable=True),
    )
    op.add_column(
        "tenants",
        sa.Column("notes", sa.Text, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tenants", "notes")
    op.drop_column("tenants", "max_courses_per_month")
    op.drop_column("tenants", "max_users")
    op.drop_column("tenants", "paid_until")
    op.drop_column("tenants", "trial_ends_at")