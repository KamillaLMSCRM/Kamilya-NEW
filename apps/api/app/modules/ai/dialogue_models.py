"""Private, server-authored selected-lesson conversation exchanges."""
from sqlalchemy import Column, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.db import Base


class LessonDialogueExchange(Base):
    __tablename__ = "ai_lesson_dialogue_exchanges"

    id = Column(UUID(as_uuid=True), primary_key=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    actor_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    course_id = Column(UUID(as_uuid=True), ForeignKey("courses.id", ondelete="CASCADE"), nullable=False)
    lesson_id = Column(UUID(as_uuid=True), ForeignKey("lessons.id", ondelete="CASCADE"), nullable=False)
    language = Column(String(2), nullable=False)
    fingerprint = Column(String(64), nullable=False)
    message = Column(Text, nullable=False)
    state = Column(String(12), nullable=False)
    response = Column(JSONB, nullable=True)
    error_code = Column(String(32), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    finished_at = Column(DateTime(timezone=True), nullable=True)
