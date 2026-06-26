"""SQLAlchemy model for `provider_keys` — encrypted API keys per provider.

For v1.0 only global keys (tenant_id NULL) are exposed via the admin UI.
The column is nullable so per-tenant override can be added in v2 without
a schema migration.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ProviderName(str, enum.Enum):
    """Allowed provider identifiers. Add new ones here, never free-form."""

    DEEPSEEK = "deepseek"
    VOYAGE = "voyage"
    # Future: OPENROUTER = "openrouter"


class ProviderKey(Base):
    """Encrypted API key for one provider.

    At most one ACTIVE key per (tenant_id, provider). Setting is_active=false
    on the current active key + inserting a new active one is the standard
    rotation pattern.
    """

    __tablename__ = "provider_keys"
    __table_args__ = (
        # A provider has at most one active key per tenant (NULL = global).
        # Postgres treats NULLs as distinct in standard UNIQUE, so we use a
        # partial unique index instead — see migration 0028.
        CheckConstraint(
            "provider IN ('deepseek', 'voyage')",
            name="ck_provider_keys_provider",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # NULL means the key is global (used by all tenants). Per-tenant
    # override is reserved for v2.
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=True,
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    # Fernet ciphertext (base64 url-safe). Decrypt via core.encryption.
    encrypted_key: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default="now()",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default="now()",
        onupdate=lambda: datetime.now(timezone.utc),
    )
    # Last successful use — useful for spotting dead keys.
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Last error message — surfaced in UI to debug misconfigured keys.
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


# Indexes are created in the migration because Alembic can't introspect
# Index objects from declarative models cleanly. The unique-active-key
# constraint is also a partial unique index, defined in 0028.