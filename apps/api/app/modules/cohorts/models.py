import uuid
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Text, UUID, UniqueConstraint, func
from app.core.db import Base


class Cohort(Base):
    __tablename__ = "cohorts"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    name = Column(Text, nullable=False)
    description = Column(Text, nullable=False, default="")
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class CohortMember(Base):
    __tablename__ = "cohort_members"
    __table_args__ = (UniqueConstraint("tenant_id", "cohort_id", "user_id", name="uq_cohort_member"),)
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    cohort_id = Column(UUID(as_uuid=True), ForeignKey("cohorts.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)


class CohortCourse(Base):
    __tablename__ = "cohort_courses"
    __table_args__ = (UniqueConstraint("tenant_id", "cohort_id", "course_id", name="uq_cohort_course"),)
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    cohort_id = Column(UUID(as_uuid=True), ForeignKey("cohorts.id", ondelete="CASCADE"), nullable=False, index=True)
    course_id = Column(UUID(as_uuid=True), ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True)
