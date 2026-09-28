from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class DocumentSourcePolicy(Base):
    __tablename__ = "document_source_policies"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    source_family_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    owner_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_review_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "source_family_id", name="uq_document_source_policy_family"),
        CheckConstraint(
            "reviewed_at IS NULL OR next_review_at IS NULL OR next_review_at >= reviewed_at",
            name="ck_document_source_policy_review_window",
        ),
        Index("ix_document_source_policy_tenant_next_review", "tenant_id", "next_review_at"),
    )


class DocumentChangeReview(Base):
    __tablename__ = "document_change_reviews"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    source_family_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    previous_document_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False
    )
    new_document_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", server_default="pending")
    added_fact_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    removed_fact_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    changed_fact_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    unchanged_fact_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    impacted_course_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    impacted_lesson_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    assessment_questions_requiring_review: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    impact_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    analysis_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    analysis_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision: Mapped[str | None] = mapped_column(String(32), nullable=True)
    decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    decided_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "previous_document_id",
            "new_document_id",
            name="uq_document_change_review_revision_pair",
        ),
        CheckConstraint(
            "status IN ('pending','processing','ready','resolved','failed')",
            name="ck_document_change_review_status",
        ),
        CheckConstraint(
            "decision IS NULL OR decision IN "
            "('no_learning_impact','update_future','update_and_retrain','suspend_old_assignments')",
            name="ck_document_change_review_decision",
        ),
        CheckConstraint(
            "added_fact_count >= 0 AND removed_fact_count >= 0 AND changed_fact_count >= 0 "
            "AND unchanged_fact_count >= 0 "
            "AND impacted_course_count >= 0 AND impacted_lesson_count >= 0 "
            "AND assessment_questions_requiring_review >= 0",
            name="ck_document_change_review_nonnegative_counts",
        ),
        CheckConstraint(
            "previous_document_id <> new_document_id",
            name="ck_document_change_review_distinct_revisions",
        ),
        CheckConstraint(
            "(status = 'resolved' AND decision IS NOT NULL AND decision_reason IS NOT NULL "
            "AND decided_at IS NOT NULL AND decision_snapshot IS NOT NULL) OR "
            "(status <> 'resolved' AND decision IS NULL AND decision_reason IS NULL "
            "AND decided_at IS NULL AND decision_snapshot IS NULL)",
            name="ck_document_change_review_resolution_state",
        ),
        Index("ix_document_change_review_tenant_status_created", "tenant_id", "status", "created_at"),
        Index("ix_document_change_review_tenant_family", "tenant_id", "source_family_id"),
    )
