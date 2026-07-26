"""Tenant-scoped rules that require a published course for an organization."""
from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, UniqueConstraint, UUID, func

from app.core.db import Base


class OrganizationCourseRule(Base):
    """A persistent organization-wide course requirement.

    Enrollment rows are materialized by ``recompute_enrollments`` rather than
    copied into the tenant's current departments. That lets future employees
    inherit the same requirement without a second configuration action.
    """

    __tablename__ = "organization_course_rules"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "course_id",
            name="uq_organization_course_rules_tenant_course",
        ),
        {"extend_existing": True},
    )

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    course_id = Column(
        UUID(as_uuid=True),
        ForeignKey("courses.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    required = Column(Boolean, nullable=False, default=True, server_default=func.true())
    created_by = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

