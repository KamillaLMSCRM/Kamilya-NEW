"""Durable notification rows for manual course assignments."""

from uuid import uuid4

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, Text, func
from sqlalchemy.dialects.postgresql import UUID

from app.core.db import Base


class CourseAssignmentNotificationOutbox(Base):
    __tablename__ = "course_assignment_notification_outbox"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    enrollment_id = Column(
        UUID(as_uuid=True), ForeignKey("enrollments.id", ondelete="RESTRICT"), nullable=False, unique=True, index=True
    )
    assigned_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    status = Column(Text, nullable=False, default="pending", server_default="pending")
    attempt_count = Column(Integer, nullable=False, default=0, server_default="0")
    next_attempt_at = Column(DateTime(timezone=True), nullable=True)
    claimed_at = Column(DateTime(timezone=True), nullable=True)
    claim_token = Column(UUID(as_uuid=True), nullable=True, unique=True)
    delivered_at = Column(DateTime(timezone=True), nullable=True)
    terminal_at = Column(DateTime(timezone=True), nullable=True)
    delivery_message_id = Column(Text, nullable=True)
    last_error_category = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','claimed','retry','delivered','dead')",
            name="ck_course_assignment_notification_status",
        ),
        CheckConstraint(
            "attempt_count >= 0 AND attempt_count <= 3",
            name="ck_course_assignment_notification_attempts",
        ),
        Index(
            "ix_course_assignment_notification_due",
            "tenant_id",
            "status",
            "next_attempt_at",
            "created_at",
        ),
    )
