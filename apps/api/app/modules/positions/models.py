import uuid
from sqlalchemy import Column, Text, UUID, DateTime, Integer, ForeignKey, func
from sqlalchemy.orm import relationship
from app.core.db import Base


class PositionCourse(Base):
    __tablename__ = "position_courses"
    __table_args__ = {'extend_existing': True}

    position_id = Column(UUID(as_uuid=True), ForeignKey("positions.id", ondelete="CASCADE"), primary_key=True)
    course_id = Column(UUID(as_uuid=True), primary_key=True)


class Position(Base):
    __tablename__ = "positions"
    __table_args__ = {'extend_existing': True}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    name = Column(Text, nullable=False)
    department = Column(Text, nullable=False, default="")
    level = Column(Text, nullable=False, default="")
    responsibilities = Column(Text, nullable=False, default="")
    requirements = Column(Text, nullable=False, default="")
    course_id = Column(UUID(as_uuid=True), nullable=True)  # legacy, kept for backward compat
    employee_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    courses = relationship("PositionCourse", primaryjoin="Position.id == PositionCourse.position_id", cascade="all, delete-orphan")
