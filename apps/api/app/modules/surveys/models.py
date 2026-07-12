import uuid
from sqlalchemy import Column, DateTime, ForeignKey, JSON, Text, UUID, UniqueConstraint, func
from app.core.db import Base


class Survey(Base):
    __tablename__ = "surveys"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    course_id = Column(UUID(as_uuid=True), ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    title = Column(Text, nullable=False)
    status = Column(Text, nullable=False, default="draft", server_default="draft")
    questions = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SurveyResponse(Base):
    __tablename__ = "survey_responses"
    __table_args__ = (UniqueConstraint("tenant_id", "survey_id", "user_id", name="uq_survey_response_user"),)
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    survey_id = Column(UUID(as_uuid=True), ForeignKey("surveys.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    answers = Column(JSON, nullable=False, default=dict)
    submitted_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
