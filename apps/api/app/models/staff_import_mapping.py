"""Staff import mapping model — reusable per-tenant column mappings.

P0.4 first-tenant hardening.

Stored mapping is a JSON object keyed by canonical field name
("personnel_number", "first_name", …) with raw column name as value.
This is the same shape that /admin/staff/import/preview already
accepts via the `mapping` form field, so we don't need any conversion
when reusing — just JSON-serialize the dict into `mapping_json`.
"""
from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.db import Base


class StaffImportMapping(Base):
    __tablename__ = "staff_import_mappings"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_staff_import_mappings_tenant_name"),
        Index("ix_staff_import_mappings_tenant_id", "tenant_id"),
        Index("ix_staff_import_mappings_tenant_created", "tenant_id", "created_at"),
        {"extend_existing": True},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid())
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    name = Column(Text, nullable=False)
    mapping_json = Column(JSONB, nullable=False, default=dict, server_default=func.text("'{}'::jsonb"))
    is_default = Column(Boolean, nullable=False, default=False, server_default=func.false())
    # No FK on created_by — circular import with app.models.users
    created_by = Column(UUID(as_uuid=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())