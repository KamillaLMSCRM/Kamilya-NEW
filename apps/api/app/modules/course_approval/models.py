from uuid import uuid4

from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.db import Base


class CourseApprovalPolicy(Base):
    __tablename__ = "course_approval_policies"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    course_id = Column(UUID(as_uuid=True), ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, unique=True)
    requires_approval = Column(Boolean, nullable=False, default=False, server_default="false")
    updated_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class CourseApprovalRevision(Base):
    __tablename__ = "course_approval_revisions"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    course_id = Column(UUID(as_uuid=True), ForeignKey("courses.id", ondelete="RESTRICT"), nullable=False, index=True)
    revision_number = Column(Integer, nullable=False)
    snapshot = Column(JSONB, nullable=False)
    snapshot_sha256 = Column(String(64), nullable=False)
    source_fingerprint = Column(String(64), nullable=False)
    state = Column(String(24), nullable=False, default="pending", server_default="pending")
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    published_release_id = Column(UUID(as_uuid=True), ForeignKey("content_releases.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        UniqueConstraint("tenant_id", "course_id", "revision_number", name="uq_course_approval_revision_number"),
        CheckConstraint("state IN ('pending','approved','changes_requested','cancelled','superseded','published')", name="ck_course_approval_revision_state"),
        CheckConstraint("snapshot_sha256 ~ '^[0-9a-f]{64}$'", name="ck_course_approval_revision_sha256"),
    )


class CourseApprovalRequest(Base):
    __tablename__ = "course_approval_requests"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    revision_id = Column(UUID(as_uuid=True), ForeignKey("course_approval_revisions.id", ondelete="CASCADE"), nullable=False, unique=True)
    requested_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    delivery_mode = Column(String(16), nullable=False)
    outcome = Column(String(24), nullable=False, default="pending", server_default="pending")
    due_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        CheckConstraint("delivery_mode IN ('email','personal_link')", name="ck_course_approval_request_delivery"),
        CheckConstraint("outcome IN ('pending','approved','changes_requested','cancelled','superseded')", name="ck_course_approval_request_outcome"),
    )


class CourseApprovalReviewer(Base):
    __tablename__ = "course_approval_reviewers"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    revision_id = Column(UUID(as_uuid=True), ForeignKey("course_approval_revisions.id", ondelete="CASCADE"), nullable=False)
    reviewer_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    required = Column(Boolean, nullable=False, default=True, server_default="true")
    decision = Column(String(24), nullable=False, default="pending", server_default="pending")
    decision_reason = Column(Text, nullable=True)
    decision_at = Column(DateTime(timezone=True), nullable=True)
    warning_acknowledged = Column(Boolean, nullable=False, default=False, server_default="false")
    __table_args__ = (
        UniqueConstraint("revision_id", "reviewer_user_id", name="uq_course_approval_reviewer"),
        CheckConstraint("decision IN ('pending','approved','changes_requested')", name="ck_course_approval_reviewer_decision"),
        CheckConstraint("decision <> 'changes_requested' OR length(btrim(decision_reason)) > 0", name="ck_course_approval_return_reason"),
    )


class CourseReviewAttempt(Base):
    __tablename__ = "course_review_attempts"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    revision_id = Column(UUID(as_uuid=True), ForeignKey("course_approval_revisions.id", ondelete="RESTRICT"), nullable=False)
    reviewer_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    purpose = Column(String(32), nullable=False, default="course_review", server_default="course_review")
    activity_state = Column(String(24), nullable=False, default="not_started", server_default="not_started")
    snapshot_sha256 = Column(String(64), nullable=False)
    lesson_position = Column(Integer, nullable=True)
    diagnostics = Column(JSONB, nullable=False, default=dict, server_default="{}")
    warning_acknowledged = Column(Boolean, nullable=False, default=False, server_default="false")
    started_at = Column(DateTime(timezone=True), nullable=True)
    last_activity_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    __table_args__ = (UniqueConstraint("revision_id", "reviewer_user_id", name="uq_course_review_attempt_reviewer"),)


class CourseReviewAttemptEvent(Base):
    __tablename__ = "course_review_attempt_events"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    attempt_id = Column(UUID(as_uuid=True), ForeignKey("course_review_attempts.id", ondelete="CASCADE"), nullable=False)
    sequence = Column(Integer, nullable=False)
    event_type = Column(String(48), nullable=False)
    payload = Column(JSONB, nullable=False, default=dict)
    payload_sha256 = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (UniqueConstraint("attempt_id", "sequence", name="uq_course_review_attempt_event_sequence"),)


class WorkflowWorkItem(Base):
    __tablename__ = "workflow_work_items"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String(24), nullable=False)
    target_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    enrollment_id = Column(UUID(as_uuid=True), ForeignKey("enrollments.id", ondelete="SET NULL"), nullable=True)
    review_revision_id = Column(UUID(as_uuid=True), ForeignKey("course_approval_revisions.id", ondelete="SET NULL"), nullable=True)
    delivery_state = Column(String(24), nullable=False, default="queued", server_default="queued")
    access_state = Column(String(24), nullable=False, default="issued", server_default="issued")
    activity_state = Column(String(24), nullable=False, default="not_started", server_default="not_started")
    deadline_state = Column(String(24), nullable=False, default="unset", server_default="unset")
    outcome = Column(String(32), nullable=False, default="pending", server_default="pending")
    due_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        CheckConstraint("(enrollment_id IS NOT NULL) <> (review_revision_id IS NOT NULL)", name="ck_work_item_exact_binding"),
        CheckConstraint("delivery_state IN ('queued','accepted','delivered','failed')", name="ck_work_item_delivery_state"),
        CheckConstraint("access_state IN ('issued','opened','pin_verified','active','expired','revoked')", name="ck_work_item_access_state"),
        CheckConstraint("activity_state IN ('not_started','in_progress','completed','decision_pending')", name="ck_work_item_activity_state"),
        CheckConstraint("deadline_state IN ('unset','scheduled','due','overdue','closed')", name="ck_work_item_deadline_state"),
        CheckConstraint("outcome IN ('pending','approved','changes_requested','cancelled','superseded')", name="ck_work_item_outcome"),
    )


class WorkflowDelivery(Base):
    __tablename__ = "workflow_deliveries"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    work_item_id = Column(UUID(as_uuid=True), ForeignKey("workflow_work_items.id", ondelete="CASCADE"), nullable=False)
    channel = Column(String(16), nullable=False)
    generation = Column(Integer, nullable=False, default=1, server_default="1")
    status = Column(String(24), nullable=False, default="queued", server_default="queued")
    attempt_count = Column(Integer, nullable=False, default=0, server_default="0")
    provider_message_id = Column(Text, nullable=True)
    error_category = Column(String(64), nullable=True)
    claim_token = Column(UUID(as_uuid=True), nullable=True)
    next_attempt_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        UniqueConstraint("work_item_id", "channel", "generation", name="uq_workflow_delivery_generation"),
        CheckConstraint("channel IN ('cabinet','email')", name="ck_workflow_delivery_channel"),
        CheckConstraint("status IN ('queued','accepted','delivered','failed')", name="ck_workflow_delivery_status"),
        CheckConstraint("attempt_count >= 0 AND attempt_count <= 8", name="ck_workflow_delivery_attempts"),
    )


class WorkflowAccessCredential(Base):
    __tablename__ = "workflow_access_credentials"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    work_item_id = Column(UUID(as_uuid=True), ForeignKey("workflow_work_items.id", ondelete="CASCADE"), nullable=False)
    reviewer_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    token_hash = Column(String(64), nullable=False, unique=True)
    pin_hash = Column(Text, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    opened_at = Column(DateTime(timezone=True), nullable=True)
    verified_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    failed_attempts = Column(Integer, nullable=False, default=0, server_default="0")
    locked_until = Column(DateTime(timezone=True), nullable=True)
    __table_args__ = (CheckConstraint("failed_attempts >= 0 AND failed_attempts <= 5", name="ck_workflow_access_failed_attempts"),)


class WorkflowReminder(Base):
    __tablename__ = "workflow_reminders"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    work_item_id = Column(UUID(as_uuid=True), ForeignKey("workflow_work_items.id", ondelete="CASCADE"), nullable=False)
    rule_key = Column(String(64), nullable=False)
    channel = Column(String(16), nullable=False, default="cabinet", server_default="cabinet")
    idempotency_key = Column(String(160), nullable=False, unique=True)
    status = Column(String(24), nullable=False, default="queued", server_default="queued")
    scheduled_at = Column(DateTime(timezone=True), nullable=False)
    __table_args__ = (CheckConstraint("channel IN ('cabinet','email')", name="ck_workflow_reminder_channel"),)


class WorkflowEscalation(Base):
    __tablename__ = "workflow_escalations"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    work_item_id = Column(UUID(as_uuid=True), ForeignKey("workflow_work_items.id", ondelete="CASCADE"), nullable=False)
    rule_key = Column(String(64), nullable=False)
    channel = Column(String(16), nullable=False, default="email", server_default="email")
    idempotency_key = Column(String(160), nullable=False, unique=True)
    status = Column(String(24), nullable=False, default="queued", server_default="queued")
    scheduled_at = Column(DateTime(timezone=True), nullable=False)
    recipient_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    __table_args__ = (CheckConstraint("channel IN ('cabinet','email')", name="ck_workflow_escalation_channel"),)
