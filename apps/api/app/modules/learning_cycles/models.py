from uuid import uuid4

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID

from app.core.db import Base


class RecurringLearningRule(Base):
    __tablename__ = "recurring_learning_rules"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    course_id = Column(UUID(as_uuid=True), ForeignKey("courses.id", ondelete="RESTRICT"), nullable=True)
    learning_path_id = Column(UUID(as_uuid=True), ForeignKey("learning_paths.id", ondelete="RESTRICT"), nullable=True)
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

    @property
    def target_type(self) -> str:
        return "learning_path" if self.learning_path_id is not None else "course"

    __table_args__ = (
        CheckConstraint(
            "(course_id IS NOT NULL AND learning_path_id IS NULL) OR "
            "(course_id IS NULL AND learning_path_id IS NOT NULL)",
            name="ck_recurring_rule_exactly_one_target",
        ),
        CheckConstraint("cadence_days BETWEEN 1 AND 3660", name="ck_recurring_rule_cadence"),
        CheckConstraint("due_days BETWEEN 0 AND 3650", name="ck_recurring_rule_due"),
        CheckConstraint("due_days <= cadence_days", name="ck_recurring_rule_due_not_after_cadence"),
        CheckConstraint("status IN ('draft','active','inactive')", name="ck_recurring_rule_status"),
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


class LearningPathCycleInstance(Base):
    """Immutable scheduled occurrence of a recurring learning-path rule."""

    __tablename__ = "learning_path_cycle_instances"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    rule_id = Column(UUID(as_uuid=True), ForeignKey("recurring_learning_rules.id", ondelete="RESTRICT"), nullable=False)
    path_id = Column(UUID(as_uuid=True), ForeignKey("learning_paths.id", ondelete="RESTRICT"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    sequence_no = Column(Integer, nullable=False)
    scheduled_for = Column(DateTime(timezone=True), nullable=False)
    starts_at = Column(DateTime(timezone=True), nullable=True)
    due_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(Text, nullable=False, default="scheduled", server_default="scheduled")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "rule_id", "sequence_no", name="uq_learning_path_cycle_instance_occurrence"),
        CheckConstraint("sequence_no >= 1", name="ck_learning_path_cycle_instance_sequence"),
        CheckConstraint(
            "status IN ('scheduled', 'active', 'completed', 'skipped', 'cancelled')",
            name="ck_learning_path_cycle_instance_status",
        ),
        CheckConstraint("due_at IS NULL OR starts_at IS NULL OR due_at >= starts_at", name="ck_learning_path_cycle_instance_dates"),
        CheckConstraint(
            "(status = 'completed' AND completed_at IS NOT NULL) OR "
            "(status <> 'completed' AND completed_at IS NULL)",
            name="ck_learning_path_cycle_instance_completion",
        ),
    )
