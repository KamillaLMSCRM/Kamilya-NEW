from sqlalchemy import Column, Text, UUID, DateTime, func, CheckConstraint
from sqlalchemy.dialects.postgresql import JSONB
from app.core.db import Base

class Course(Base):
    __tablename__ = "courses"

    id = Column(UUID(as_uuid=True), primary_key=True)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    title = Column(Text, nullable=False)
    description = Column(Text, nullable=False, default="")
    status = Column(Text, nullable=False, default="draft")
    thumbnail_url = Column(Text, nullable=True)
    created_by = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    published_at = Column(DateTime(timezone=True), nullable=True)
    ai_generated = Column(Text, nullable=False, default="false")

    __table_args__ = (
        CheckConstraint("status IN ('draft', 'published', 'archived')", name="ck_course_status"),
    )
