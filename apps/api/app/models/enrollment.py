"""Enrollment model"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, String, Text
from sqlalchemy.dialects.postgresql import UUID

from app.core.db import Base


class Enrollment(Base):
    __tablename__ = "enrollments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    course_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    status = Column(String, nullable=False, default="enrolled")
    enrolled_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime(timezone=True), nullable=True)
    # How this enrollment came to exist. 'manual' = via /admin/enrollments
    # (ad-hoc by methodologist/HR). 'position' = materialized from
    # PositionCourse. 'department' = materialized from DepartmentCourse.
    # The recompute_enrollments kernel only manages 'position' and
    # 'department' rows; 'manual' is user-driven and never auto-removed.
    source = Column(Text, nullable=False, default="manual", server_default="manual")
