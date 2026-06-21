"""Generated Content model"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, JSON
from sqlalchemy.dialects.postgresql import UUID
from app.core.db import Base


class GeneratedContent(Base):
    __tablename__ = "generated_content"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(String, nullable=False, index=True)
    course_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    content_type = Column(String, nullable=False)
    title = Column(String, nullable=False)
    content = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
