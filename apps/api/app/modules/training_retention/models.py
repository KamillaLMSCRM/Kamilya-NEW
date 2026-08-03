"""Database model for tenant-owned evidence retention policies."""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID

from app.core.db import Base


class TrainingRetentionPolicy(Base):
    __tablename__ = "training_retention_policies"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "procedure_type",
            name="uq_training_retention_policies_tenant_procedure",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid())
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True)
    procedure_type = Column(Text, nullable=False, index=True)
    retention_days = Column(Integer, nullable=False)
    legal_basis = Column(Text, nullable=True)
    local_basis = Column(Text, nullable=True)
    active = Column(Boolean, nullable=False, default=False, server_default="false", index=True)
    created_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    updated_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
