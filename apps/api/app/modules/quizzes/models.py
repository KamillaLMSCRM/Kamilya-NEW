"""Quiz models"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, Boolean, DateTime, Text, ForeignKey, JSON
from sqlalchemy.dialects.postgresql import UUID
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
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


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
    score_percent = Column("score", Integer, nullable=False, default=0)
    total_points = Column(Integer, nullable=False, default=0)
    earned_points = Column(Integer, nullable=False, default=0)
    passed = Column(Boolean, nullable=False, default=False)
    answers = Column(JSON, nullable=False, default=list)
    started_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime(timezone=True), nullable=True)
    time_spent_seconds = Column(Integer, nullable=True)
