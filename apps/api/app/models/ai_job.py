"""AI Job model"""
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, Text, DateTime, JSON
from sqlalchemy.dialects.postgresql import UUID
from app.core.db import Base


class AIJob(Base):
    __tablename__ = "ai_jobs"

    id = Column(String, primary_key=True)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    course_id = Column(UUID(as_uuid=True), nullable=True)
    status = Column(String, nullable=False, default="pending")
    stage = Column(String, nullable=False, default="queued")
    progress = Column(Integer, nullable=False, default=0)
    message = Column(Text, nullable=True)
    params = Column(JSON, nullable=True)
    result = Column(JSON, nullable=True)
    errors = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
