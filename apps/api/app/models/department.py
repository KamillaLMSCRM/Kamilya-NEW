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
  - `code`, `head_user_id`, `description`, `created_at` — present
    in the DB schema (added by migration 0035 / 0036 / 0037). The
    ORM was missing them until 2026-06-30, which meant any read of
    `Department.created_at` raised AttributeError even though the
    column exists. Now declared.
"""
import uuid

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID

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
    description = Column(Text, nullable=True)
    code = Column(Text, nullable=True)
    head_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    parent_id = Column(
        UUID(as_uuid=True),
        ForeignKey("departments.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )