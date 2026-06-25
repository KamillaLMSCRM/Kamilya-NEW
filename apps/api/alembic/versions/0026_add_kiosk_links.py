"""add kiosk_links table

Stage 1b of employee onboarding epic (docs/plans/employee-onboarding.md).

kiosk_links
- Single shareable URL per kiosk (HR prints as QR code, posts on workshop wall)
- Worker identifies by personnel_number → sees assigned courses → takes them
  on the kiosk (tablet/phone shared device)
- Inspired by EasyLlama's "Kiosk Link" feature (1 link per workshop)

scope_position_id (nullable):
- If set: only users with this position_id can identify at this kiosk
- If null: any active user in the tenant can identify (general training kiosk)

location (free text): where the kiosk physically lives ("Цех №1, Алматы"),
helps HR distinguish multiple kiosk links visually but isn't enforced server-side.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID, JSONB


revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "kiosk_links",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("token", sa.Text, nullable=False, unique=True),
        sa.Column("location", sa.Text, nullable=True),  # free text, e.g. "Цех №1, Алматы"
        sa.Column("scope_position_id", UUID(as_uuid=True), nullable=True),  # NULL = any active user in tenant
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_by", UUID(as_uuid=True), nullable=False),  # FK users
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),  # optional kiosk lifetime
    )
    op.create_index(
        "ix_kiosk_links_tenant_active",
        "kiosk_links",
        ["tenant_id", "is_active"],
    )


def downgrade() -> None:
    op.drop_index("ix_kiosk_links_tenant_active", table_name="kiosk_links")
    op.drop_table("kiosk_links")
