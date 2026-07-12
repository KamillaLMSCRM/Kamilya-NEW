import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, Text, UUID, func
from app.core.db import Base


class Announcement(Base):
    __tablename__ = "announcements"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    course_id = Column(UUID(as_uuid=True), ForeignKey("courses.id", ondelete="SET NULL"), nullable=True, index=True)
    title = Column(Text, nullable=False)
    body = Column(Text, nullable=False)
    status = Column(Text, nullable=False, default="draft", server_default="draft")
    recipients_count = Column(Integer, nullable=False, default=0, server_default="0")
    sent_count = Column(Integer, nullable=False, default=0, server_default="0")
    failed_count = Column(Integer, nullable=False, default=0, server_default="0")
    sent_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    result = Column(JSON, nullable=True)
