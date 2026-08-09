from uuid import uuid4

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID

from app.core.db import Base


class RecurringLearningRule(Base):
    __tablename__ = "recurring_learning_rules"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    course_id = Column(UUID(as_uuid=True), ForeignKey("courses.id", ondelete="RESTRICT"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    cadence_days = Column(Integer, nullable=False)
    due_days = Column(Integer, nullable=False)
    status = Column(Text, nullable=False, default="draft", server_default="draft")
    next_run_at = Column(DateTime(timezone=True), nullable=True)
    last_run_at = Column(DateTime(timezone=True), nullable=True)
    claimed_at = Column(DateTime(timezone=True), nullable=True)
    claim_token = Column(UUID(as_uuid=True), nullable=True, unique=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    __table_args__ = (
        CheckConstraint("cadence_days BETWEEN 1 AND 3660", name="ck_recurring_rule_cadence"),
        CheckConstraint("due_days BETWEEN 0 AND 365", name="ck_recurring_rule_due"),
        CheckConstraint("status IN ('draft','active','inactive')", name="ck_recurring_rule_status"),
        UniqueConstraint("tenant_id", "course_id", "user_id", name="uq_recurring_rule_course_user"),
    )


class RecurringLearningAssignment(Base):
    __tablename__ = "recurring_learning_assignments"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    rule_id = Column(UUID(as_uuid=True), ForeignKey("recurring_learning_rules.id", ondelete="RESTRICT"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    course_id = Column(UUID(as_uuid=True), ForeignKey("courses.id", ondelete="RESTRICT"), nullable=False)
    enrollment_id = Column(UUID(as_uuid=True), ForeignKey("enrollments.id", ondelete="RESTRICT"), nullable=True)
    scheduled_for = Column(DateTime(timezone=True), nullable=False)
    due_at = Column(DateTime(timezone=True), nullable=False)
    status = Column(Text, nullable=False, default="assigned", server_default="assigned")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        CheckConstraint("status IN ('assigned','completed','skipped')", name="ck_recurring_assignment_status"),
        UniqueConstraint("rule_id", "scheduled_for", name="uq_recurring_assignment_run"),
    )
