"""Tenant-owned delivery and time policy for one learner enrollment."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID

from app.core.db import Base


class EnrollmentAccessPolicy(Base):
    __tablename__ = "enrollment_access_policies"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    enrollment_id = Column(
        UUID(as_uuid=True), ForeignKey("enrollments.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    delivery_mode = Column(String, nullable=False, default="email", server_default="email")
    link_expires_at = Column(DateTime(timezone=True), nullable=True)
    completion_window_minutes = Column(Integer, nullable=True)
    completion_window_started_at = Column(DateTime(timezone=True), nullable=True)
    completion_window_expires_at = Column(DateTime(timezone=True), nullable=True)
    due_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    revoked_reason = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
    updated_at = Column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )
