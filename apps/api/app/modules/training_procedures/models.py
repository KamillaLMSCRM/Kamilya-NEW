"""Tenant-owned configuration for non-system training procedures."""

from __future__ import annotations

import uuid

from sqlalchemy import (
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.db import Base


class TrainingProcedure(Base):
    """A versioned procedure definition; it does not create evidence events."""

    __tablename__ = "training_procedures"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "code",
            "version",
            name="uq_training_procedures_tenant_code_version",
        ),
        CheckConstraint(
            "code ~ '^[a-z0-9][a-z0-9._-]{0,99}$'",
            name="ck_training_procedures_code_format",
        ),
        Index(
            "uq_training_procedures_one_active_code",
            "tenant_id",
            "code",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid())
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True)
    code = Column(Text, nullable=False)
    version = Column(Integer, nullable=False)
    title = Column(Text, nullable=False)
    description = Column(Text, nullable=False, default="", server_default="")
    procedure_type = Column(Text, nullable=False, index=True)
    status = Column(Text, nullable=False, default="draft", server_default="draft", index=True)
    approval_reference = Column(Text, nullable=True)
    approval_date = Column(Date, nullable=True)
    approved_by_name = Column(Text, nullable=True)
    legal_basis = Column(Text, nullable=True)
    local_basis = Column(Text, nullable=True)
    confirmation_method = Column(Text, nullable=False)
    retention_class = Column(Text, nullable=True)
    retention_days = Column(Integer, nullable=True)
    commission_snapshot_rules = Column(JSONB, nullable=True)
    authorized_decision_rules = Column(JSONB, nullable=True)
    created_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    updated_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    activated_at = Column(DateTime(timezone=True), nullable=True)
    retired_at = Column(DateTime(timezone=True), nullable=True)
