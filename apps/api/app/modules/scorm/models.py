from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.db import Base


class ScormPackage(Base):
    __tablename__ = "scorm_packages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    course_id = Column(UUID(as_uuid=True), ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True)
    version = Column(Text, nullable=False, default="scorm_1_2")
    title = Column(Text, nullable=False)
    entrypoint = Column(Text, nullable=False)
    storage_key = Column(Text, nullable=False)
    manifest_json = Column(JSONB, nullable=False, default=dict)
    uploaded_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ScormAttempt(Base):
    __tablename__ = "scorm_attempts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    course_id = Column(UUID(as_uuid=True), ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True)
    package_id = Column(UUID(as_uuid=True), ForeignKey("scorm_packages.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    lesson_status = Column(Text, nullable=True)
    success_status = Column(Text, nullable=True)
    completion_status = Column(Text, nullable=True)
    score_raw = Column(Text, nullable=True)
    lesson_location = Column(Text, nullable=True)
    total_time = Column(Text, nullable=True)
    suspend_data = Column(Text, nullable=True)
    cmi_json = Column(JSONB, nullable=False, default=dict)
    started_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_commit_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

