"""Enrollment model"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID

from app.core.db import Base


class Enrollment(Base):
    __tablename__ = "enrollments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    course_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    content_release_id = Column(
        UUID(as_uuid=True),
        ForeignKey("content_releases.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    status = Column(String, nullable=False, default="enrolled")
    enrolled_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime(timezone=True), nullable=True)
    # How this enrollment came to exist. The rule kernel manages only
    # position, department and organization rows. Manual, cohort,
    # learning_path and future unknown sources are protected from rule
    # recomputation.
    source = Column(Text, nullable=False, default="manual", server_default="manual")
