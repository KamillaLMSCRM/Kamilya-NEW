"""add provider_keys table for superadmin-managed API credentials

Adds the `provider_keys` table for storing encrypted API keys for cloud
LLM/embedding providers (DeepSeek, Voyage, future OpenRouter).

Schema:
- id          UUID PK
- tenant_id   UUID NULL (FK tenants) — NULL means global
- provider    String(32) — 'deepseek' | 'voyage'
- encrypted_key Text — Fernet ciphertext (base64 url-safe)
- label       String(128) NULL — human description
- is_active   Boolean — at most one active per (tenant, provider)
- created_by  UUID NULL (FK users)
- created_at  / updated_at timestamps
- last_used_at / last_error — ops visibility

Multi-tenancy:
For v1.0 only global keys (tenant_id IS NULL) are exposed via the UI.
Per-tenant override is reserved for v2 but the column is already nullable.

Security:
The plaintext key never leaves the server. The UI shows only a masked
preview (mask_secret in app/core/encryption.py). PROVIDER_KEY_ENCRYPTION_KEY
(env var) is the Fernet master key — losing it makes all stored keys
unreadable. Keep an offline backup.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID


revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "provider_keys",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("encrypted_key", sa.Text, nullable=False),
        sa.Column("label", sa.String(128), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean,
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "created_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.CheckConstraint(
            "provider IN ('deepseek', 'voyage')",
            name="ck_provider_keys_provider",
        ),
    )

    # Standard btree on tenant_id for the common "list by tenant" path.
    op.create_index(
        "ix_provider_keys_tenant_id",
        "provider_keys",
        ["tenant_id"],
    )
    op.create_index(
        "ix_provider_keys_provider",
        "provider_keys",
        ["provider"],
    )

    # Partial unique index enforcing "at most one active key per
    # (tenant_id, provider)". Postgres standard UNIQUE treats NULLs as
    # distinct, so this is the cleanest way to also allow per-tenant rows
    # later without conflict.
    op.execute(
        """
        CREATE UNIQUE INDEX uq_provider_keys_active_per_tenant
        ON provider_keys (provider, COALESCE(tenant_id, '00000000-0000-0000-0000-000000000000'::uuid))
        WHERE is_active = true
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_provider_keys_active_per_tenant")
    op.drop_index("ix_provider_keys_provider", table_name="provider_keys")
    op.drop_index("ix_provider_keys_tenant_id", table_name="provider_keys")
    op.drop_table("provider_keys")