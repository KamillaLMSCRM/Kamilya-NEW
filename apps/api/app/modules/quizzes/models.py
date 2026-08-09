"""Quiz models"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.db import Base


class Quiz(Base):
    __tablename__ = "quizzes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lesson_id = Column(UUID(as_uuid=True), ForeignKey("lessons.id", ondelete="cascade"), nullable=False, index=True)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    title = Column(String, nullable=False)
    pass_score = Column(Integer, nullable=False, default=80)
    time_limit = Column(Integer, nullable=True)
    attempt_limit = Column(Integer, nullable=False, default=3)
    deferral_days = Column(Integer, nullable=False, default=7)
    review_status = Column(String, nullable=False, default="approved", server_default="approved")
    reviewed_by = Column(UUID(as_uuid=True), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class Question(Base):
    __tablename__ = "questions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    quiz_id = Column(UUID(as_uuid=True), ForeignKey("quizzes.id", ondelete="cascade"), nullable=False, index=True)
    text = Column(Text, nullable=False)
    type = Column(String, nullable=False)
    points = Column(Integer, nullable=False, default=1)
    explanation = Column(Text, nullable=True)
    order_index = Column(Integer, nullable=False, default=0)
    pool_group = Column(String, nullable=True)


class QuizChoice(Base):
    __tablename__ = "quiz_choices"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    question_id = Column(UUID(as_uuid=True), ForeignKey("questions.id", ondelete="cascade"), nullable=False, index=True)
    text = Column(Text, nullable=False)
    is_correct = Column(Boolean, nullable=False, default=False)
    order_index = Column(Integer, nullable=False, default=0)


class QuizAttempt(Base):
    __tablename__ = "quiz_attempts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    quiz_id = Column(UUID(as_uuid=True), ForeignKey("quizzes.id", ondelete="cascade"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    enrollment_id = Column(
        UUID(as_uuid=True),
        ForeignKey("enrollments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    content_release_id = Column(
        UUID(as_uuid=True),
        ForeignKey("content_releases.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    score_percent = Column(Integer, nullable=False, default=0)
    total_points = Column(Integer, nullable=False, default=0)
    earned_points = Column(Integer, nullable=False, default=0)
    passed = Column(Boolean, nullable=False, default=False)
    answers = Column(JSON, nullable=False, default=list)
    evidence_snapshot = Column(JSONB, nullable=True)
    evidence_sha256 = Column(String(64), nullable=True)
    started_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    completed_at = Column(DateTime(timezone=True), nullable=True)
    time_spent_seconds = Column(Integer, nullable=True)
