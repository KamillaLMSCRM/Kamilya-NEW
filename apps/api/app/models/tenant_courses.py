"""TenantCourse model — level-1 (tenant-wide) course assignment rule.

A row in this table means: every user in this tenant gets
enrolled in this course (subject to recompute_enrollments
priority: position > department > tenant; manual and
completed are protected).

Mirrors PositionCourse / DepartmentCourse pattern. The
(composite) PK (tenant_id, course_id) makes inserts
idempotent at the DB level via ON CONFLICT DO NOTHING.

Lesson 22 (docs/LESSONS.md, 2026-06-30) documents the 4-level
package model. This is level 1 (broadest). Manual
enrollments (source='manual') are level 4 (most specific,
never auto-managed).
"""
import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID

from app.core.db import Base


class TenantCourse(Base):
    __tablename__ = "tenant_courses"
    __table_args__ = {'extend_existing': True}

    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        primary_key=True,
    )
    course_id = Column(UUID(as_uuid=True), primary_key=True)
    # Whether this course counts toward the tenant's ready_percent
    # denominator. required=True (default): counts.
    # required=False: enrolled but excluded. Same semantics as
    # PositionCourse.required / DepartmentCourse.required.
    required = Column(
        Boolean, nullable=False, default=True, server_default=func.true()
    )
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
