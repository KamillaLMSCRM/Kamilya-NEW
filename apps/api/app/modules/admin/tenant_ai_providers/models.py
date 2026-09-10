"""ORM model for the tenant-scoped BYOK provider settings."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class TenantAIProvider(Base):
    __tablename__ = "tenant_ai_providers"
    __table_args__ = (
        UniqueConstraint("tenant_id", "purpose", name="uq_tenant_ai_providers_tenant_purpose"),
        CheckConstraint("purpose IN ('generation', 'embedding')", name="ck_tenant_ai_providers_purpose"),
        CheckConstraint("provider IN ('deepseek', 'openrouter', 'voyage', 'cohere')", name="ck_tenant_ai_providers_provider"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    purpose: Mapped[str] = mapped_column(String(16), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    encrypted_key: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    free_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    output_dimensions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC), server_default="now()")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC), server_default="now()", onupdate=lambda: datetime.now(UTC))
