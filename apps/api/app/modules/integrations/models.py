"""Tenant integrations — per-tenant credentials for SMTP/Telegram/WhatsApp.

Schema:
  tenant_integrations
    id              UUID PK
    tenant_id       UUID FK
    channel         'smtp' | 'telegram' | 'whatsapp'
    config_encrypted BYTEA  (Fernet-encrypted JSON of channel-specific fields)
    is_active       BOOL
    last_test_at    TIMESTAMPTZ
    last_test_status TEXT   ('ok' | 'failed: ...')
    created_at, updated_at

  tenant_integrations_audit
    id              UUID PK
    tenant_id       UUID
    channel         ...
    changed_by      UUID FK users
    change_type     'created' | 'updated' | 'deleted' | 'test_passed' | 'test_failed'
    metadata        JSONB
    created_at

Security:
  - config_encrypted is Fernet-encrypted with MASTER_ENCRYPTION_KEY
    (from env). Loss of master key = all tenant creds unreadable.
  - Per-channel config shape:
      smtp:      { host, port, username, password, from_addr, from_name, use_tls }
      telegram:  { bot_token }
      whatsapp:  {} (no creds in DB — they're on wa-gateway disk)
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Index, String, Text, func,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB, BYTEA
from sqlalchemy import UniqueConstraint

from app.core.db import Base


class TenantIntegration(Base):
    """One row per (tenant, channel) — channel-specific config."""
    __tablename__ = "tenant_integrations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "channel", name="uq_tenant_channel"),
        Index("idx_tenant_integrations_active", "tenant_id", "is_active"),
        {"extend_existing": True},
    )

    id = Column(UUID(as_uuid=True), primary_key=True,
                default=uuid.uuid4, server_default=func.gen_random_uuid())
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    channel = Column(String(32), nullable=False)  # 'smtp' | 'telegram' | 'whatsapp'
    config_encrypted = Column(BYTEA, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    last_test_at = Column(DateTime(timezone=True), nullable=True)
    last_test_status = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False,
                        server_default=func.now(), onupdate=func.now())


class TenantIntegrationAudit(Base):
    """Append-only audit log of integration changes.

    Why separate table? Lets ops query "who changed SMTP password last
    week" without scanning the encrypted config blob. Also supports
    compliance audits (GDPR/KZ data residency).
    """
    __tablename__ = "tenant_integrations_audit"
    __table_args__ = (
        Index("idx_audit_tenant_created", "tenant_id", "created_at"),
        {"extend_existing": True},
    )

    id = Column(UUID(as_uuid=True), primary_key=True,
                default=uuid.uuid4, server_default=func.gen_random_uuid())
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    channel = Column(String(32), nullable=False)
    changed_by = Column(UUID(as_uuid=True), nullable=False)
    change_type = Column(String(32), nullable=False)
    metadata_json = Column("metadata", JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())