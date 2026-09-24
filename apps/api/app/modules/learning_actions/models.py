from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class LearningAction(Base):
    __tablename__ = "learning_actions"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    target_type: Mapped[str] = mapped_column(String(16), nullable=False)
    target_key: Mapped[str] = mapped_column(String(320), nullable=False)
    enrollment_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    course_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    quiz_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    content_release_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    question_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    question_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    issue_type: Mapped[str] = mapped_column(String(32), nullable=False)
    action_type: Mapped[str] = mapped_column(String(32), nullable=False)
    owner_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    baseline_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    outcome_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open", server_default="open")
    resolution: Mapped[str | None] = mapped_column(String(16), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("target_type IN ('enrollment','question')", name="ck_learning_action_target_type"),
        CheckConstraint(
            "issue_type IN ('not_started','stalled','overdue','failed_required_quiz','weak_question')",
            name="ck_learning_action_issue_type",
        ),
        CheckConstraint(
            "action_type IN ('reminder','reassignment','supplemental_material','manual_review')",
            name="ck_learning_action_action_type",
        ),
        CheckConstraint("status IN ('open','completed','cancelled')", name="ck_learning_action_status"),
        CheckConstraint(
            "resolution IS NULL OR resolution IN ('observed','manual','cancelled')",
            name="ck_learning_action_resolution",
        ),
        CheckConstraint(
            "(target_type = 'enrollment' AND enrollment_id IS NOT NULL AND quiz_id IS NULL AND content_release_id IS NULL AND question_id IS NULL AND question_key IS NULL AND issue_type <> 'weak_question') OR "
            "(target_type = 'question' AND enrollment_id IS NULL AND quiz_id IS NOT NULL AND question_id IS NOT NULL AND question_key ~ '^[0-9a-f]{64}$' AND issue_type = 'weak_question')",
            name="ck_learning_action_target_identity",
        ),
        CheckConstraint(
            "(status = 'open' AND resolution IS NULL AND closed_at IS NULL AND outcome_snapshot IS NULL) OR "
            "(status <> 'open' AND resolution IS NOT NULL AND closed_at IS NOT NULL AND outcome_snapshot IS NOT NULL)",
            name="ck_learning_action_closure_state",
        ),
        Index(
            "uq_learning_action_active_target_issue_action",
            "tenant_id",
            "target_key",
            "issue_type",
            "action_type",
            unique=True,
            postgresql_where=(status == "open"),
        ),
        Index("ix_learning_action_tenant_status_created", "tenant_id", "status", "created_at"),
    )


class LearningActionEvent(Base):
    __tablename__ = "learning_action_events"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    action_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("learning_actions.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint("event_type IN ('created','closed')", name="ck_learning_action_event_type"),
        UniqueConstraint("tenant_id", "action_id", "event_type", name="uq_learning_action_event_transition"),
        Index("ix_learning_action_event_tenant_created", "tenant_id", "created_at"),
    )
