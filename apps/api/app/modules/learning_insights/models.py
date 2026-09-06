"""Methodologist decisions kept separate from immutable assessment evidence."""

from uuid import uuid4

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID

from app.core.db import Base


class LearningQuestionReview(Base):
    __tablename__ = "learning_question_reviews"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    course_id = Column(UUID(as_uuid=True), ForeignKey("courses.id", ondelete="CASCADE"), nullable=False)
    question_key = Column(String(64), nullable=False)
    status = Column(String(32), nullable=False, default="unreviewed", server_default="unreviewed")
    updated_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_id", "course_id", "question_key", name="uq_learning_question_review"),
        CheckConstraint(
            "status IN ('unreviewed','train_staff','review_question','improve_material','resolved')",
            name="ck_learning_question_review_status",
        ),
        CheckConstraint("question_key ~ '^[0-9a-f]{64}$'", name="ck_learning_question_review_key"),
    )
