"""Department — normalized org-chart node (ADR-0011).

Replaces the free-text `Position.department` string with a proper
table that has:

  - `slug` — lowercase canonical form ("hr", "it", "finance").
    Uniqueness enforced per tenant so "HR" and "hr" collapse to the
    same row when ingested through the staff-import wizard.
  - `parent_id` — nullable self-reference for future hierarchy
    (parent = "Engineering" → child = "Backend"). v1.0 doesn't
    expose this in the UI; the field exists so we don't need a
    migration when we add it in v1.1.
"""
import uuid
from sqlalchemy import Column, Text, ForeignKey, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.core.db import Base


class Department(Base):
    __tablename__ = "departments"
    __table_args__ = (
        UniqueConstraint("tenant_id", "slug", name="uq_departments_tenant_slug"),
        Index("idx_departments_tenant", "tenant_id"),
        {"extend_existing": True},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    name = Column(Text, nullable=False)  # display name "Human Resources"
    slug = Column(Text, nullable=False)  # canonical "hr"
    parent_id = Column(
        UUID(as_uuid=True),
        ForeignKey("departments.id", ondelete="SET NULL"),
        nullable=True,
    )