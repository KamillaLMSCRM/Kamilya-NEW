from uuid import uuid4

from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Integer, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.db import Base


class LearningPath(Base):
    __tablename__ = "learning_paths"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    title = Column(Text, nullable=False)
    description = Column(Text, nullable=False, default="")
    status = Column(Text, nullable=False, default="draft", server_default="draft")
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    courses = relationship(
        "LearningPathCourse",
        back_populates="path",
        cascade="all, delete-orphan",
        order_by="LearningPathCourse.order_index",
    )

    __table_args__ = (
        CheckConstraint("status IN ('draft', 'published', 'archived')", name="ck_learning_path_status"),
    )


class LearningPathCourse(Base):
    __tablename__ = "learning_path_courses"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    path_id = Column(UUID(as_uuid=True), ForeignKey("learning_paths.id", ondelete="CASCADE"), nullable=False, index=True)
    course_id = Column(UUID(as_uuid=True), ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True)
    order_index = Column(Integer, nullable=False)
    required = Column(Boolean, nullable=False, default=True, server_default="true")

    path = relationship("LearningPath", back_populates="courses")
    course = relationship("Course")

    __table_args__ = (
        UniqueConstraint("path_id", "course_id", name="uq_learning_path_course"),
        UniqueConstraint("path_id", "order_index", name="uq_learning_path_order"),
    )
