"""Persistence for standalone checks; migration owns database constraints."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.db import Base


class KnowledgeCheck(Base):
    __tablename__ = "knowledge_checks"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_knowledge_checks_tenant_id"),
        CheckConstraint("revision > 0 AND status IN ('draft','published')", name="ck_knowledge_checks_state"),
        CheckConstraint("jsonb_typeof(content)='object' AND length(create_sha256)=64", name="ck_knowledge_checks_content"),
        Index("ix_knowledge_checks_tenant_created", "tenant_id", "created_at"),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False)
    content = Column(JSONB, nullable=False)
    create_sha256 = Column(String(64), nullable=False)
    revision = Column(Integer, nullable=False, default=1)
    status = Column(String, nullable=False, default="draft")
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))


class KnowledgeCheckAssignment(Base):
    __tablename__ = "knowledge_check_assignments"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "check_id"], ["knowledge_checks.tenant_id", "knowledge_checks.id"], ondelete="RESTRICT"),
        UniqueConstraint("tenant_id", "id", name="uq_knowledge_assignment_tenant_id"),
        UniqueConstraint("check_id", "revision", "user_id", name="uq_knowledge_assignment_revision_user"),
        CheckConstraint("revision > 0 AND length(snapshot_sha256)=64 AND jsonb_typeof(snapshot)='object'", name="ck_knowledge_assignment_snapshot"),
        Index("ix_knowledge_assignment_user", "tenant_id", "user_id", "created_at"),
        Index("ix_knowledge_assignment_check", "tenant_id", "check_id", "created_at"),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False)
    check_id = Column(UUID(as_uuid=True), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    assigned_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    revision = Column(Integer, nullable=False)
    snapshot = Column(JSONB, nullable=False)
    snapshot_sha256 = Column(String(64), nullable=False)
    due_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))


class KnowledgeCheckAttempt(Base):
    __tablename__ = "knowledge_check_attempts"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "assignment_id"], ["knowledge_check_assignments.tenant_id", "knowledge_check_assignments.id"], ondelete="RESTRICT"),
        UniqueConstraint("assignment_id", "number", name="uq_knowledge_attempt_number"),
        CheckConstraint("number>0 AND length(snapshot_sha256)=64", name="ck_knowledge_attempt_identity"),
        CheckConstraint("status IN ('started','submitted','expired')", name="ck_knowledge_attempt_status"),
        CheckConstraint("(status='started' AND completed_at IS NULL AND score_percent IS NULL AND passed IS NULL AND earned_points IS NULL AND total_points IS NULL AND submission_sha256 IS NULL) OR (status IN ('submitted','expired') AND completed_at IS NOT NULL AND score_percent IS NOT NULL AND score_percent BETWEEN 0 AND 100 AND passed IS NOT NULL AND earned_points IS NOT NULL AND total_points IS NOT NULL AND earned_points>=0 AND total_points>0 AND earned_points<=total_points AND submission_sha256 IS NOT NULL AND length(submission_sha256)=64)", name="ck_knowledge_attempt_result"),
        Index("ix_knowledge_attempt_assignment", "tenant_id", "assignment_id"),
        Index("uq_knowledge_active_attempt", "assignment_id", unique=True, postgresql_where=text("status='started'")),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False)
    assignment_id = Column(UUID(as_uuid=True), nullable=False)
    number = Column(Integer, nullable=False)
    snapshot = Column(JSONB, nullable=False)
    snapshot_sha256 = Column(String(64), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
    deadline_at = Column(DateTime(timezone=True))
    answers = Column(JSONB, nullable=False, default=list)
    submission_sha256 = Column(String(64))
    status = Column(String, nullable=False, default="started")
    completed_at = Column(DateTime(timezone=True))
    score_percent = Column(Integer)
    passed = Column(Boolean)
    earned_points = Column(Integer)
    total_points = Column(Integer)
