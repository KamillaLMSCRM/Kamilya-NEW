"""add tenant_integrations + audit tables

Sprint 2 of multi-channel-delivery epic (ADR-0010). Stores per-tenant
credentials for SMTP/Telegram/WhatsApp channels.

Design:
  - config_encrypted: BYTEA with Fernet-encrypted JSON blob
    (MASTER_ENCRYPTION_KEY in env). Decryption lives in
    app.modules.integrations.crypto.
  - One row per (tenant_id, channel) — enforced by uq_tenant_channel.
  - Append-only audit table for compliance / GDPR data-residency audits.

WhatsApp has no creds in DB — the gateway holds creds.json on disk.
We store `{ gateway_managed: true }` as a marker so the integrations
list shows it as configured.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID, JSONB, BYTEA


revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenant_integrations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("config_encrypted", BYTEA, nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("last_test_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_test_status", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.UniqueConstraint("tenant_id", "channel", name="uq_tenant_channel"),
    )
    op.create_index("idx_tenant_integrations_tenant_id",
                    "tenant_integrations", ["tenant_id"])
    op.create_index("idx_tenant_integrations_active",
                    "tenant_integrations", ["tenant_id", "is_active"])

    op.create_table(
        "tenant_integrations_audit",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("changed_by", UUID(as_uuid=True), nullable=False),
        sa.Column("change_type", sa.String(32), nullable=False),
        sa.Column("metadata", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )
    op.create_index("idx_audit_tenant_created",
                    "tenant_integrations_audit", ["tenant_id", "created_at"])


def downgrade() -> None:
    op.drop_index("idx_audit_tenant_created", table_name="tenant_integrations_audit")
    op.drop_table("tenant_integrations_audit")
    op.drop_index("idx_tenant_integrations_active", table_name="tenant_integrations")
    op.drop_index("idx_tenant_integrations_tenant_id", table_name="tenant_integrations")
    op.drop_table("tenant_integrations")