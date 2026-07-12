import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Integer, Text, UniqueConstraint, UUID, func
from sqlalchemy.orm import relationship

from app.core.db import Base
from app.models.courses import Course  # noqa: F401
from app.modules.positions.models import Position  # noqa: F401


class Competency(Base):
    __tablename__ = "competencies"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_competencies_tenant_name"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    name = Column(Text, nullable=False)
    description = Column(Text, nullable=False, default="")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    position_links = relationship("PositionCompetency", back_populates="competency", cascade="all, delete-orphan")
    course_links = relationship("CompetencyCourse", back_populates="competency", cascade="all, delete-orphan")


class PositionCompetency(Base):
    __tablename__ = "position_competencies"
    __table_args__ = (UniqueConstraint("tenant_id", "position_id", "competency_id", name="uq_position_competency"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    position_id = Column(UUID(as_uuid=True), ForeignKey("positions.id", ondelete="CASCADE"), nullable=False, index=True)
    competency_id = Column(UUID(as_uuid=True), ForeignKey("competencies.id", ondelete="CASCADE"), nullable=False, index=True)
    required_level = Column(Integer, nullable=False, default=1, server_default="1")
    competency = relationship("Competency", back_populates="position_links")
    position = relationship("Position")


class CompetencyCourse(Base):
    __tablename__ = "competency_courses"
    __table_args__ = (UniqueConstraint("tenant_id", "competency_id", "course_id", name="uq_competency_course"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    competency_id = Column(UUID(as_uuid=True), ForeignKey("competencies.id", ondelete="CASCADE"), nullable=False, index=True)
    course_id = Column(UUID(as_uuid=True), ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True)
    competency = relationship("Competency", back_populates="course_links")
    course = relationship("Course")
