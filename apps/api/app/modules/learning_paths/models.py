from uuid import uuid4

from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Integer, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.db import Base


class LearningPath(Base):
    __tablename__ = "learning_paths"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    # A family represents one logical learning program. Published versions are
    # immutable snapshots; new work is done in a draft version in the same family.
    family_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    version = Column(Integer, nullable=False, default=1, server_default="1")
    title = Column(Text, nullable=False)
    description = Column(Text, nullable=False, default="")
    status = Column(Text, nullable=False, default="draft", server_default="draft")
    sequencing_mode = Column(Text, nullable=False, default="linear", server_default="linear")
    published_at = Column(DateTime(timezone=True), nullable=True)
    supersedes_id = Column(UUID(as_uuid=True), ForeignKey("learning_paths.id", ondelete="SET NULL"), nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    courses = relationship(
        "LearningPathCourse",
        back_populates="path",
        cascade="all, delete-orphan",
        order_by="LearningPathCourse.order_index",
    )
    assignments = relationship(
        "LearningPathAssignment",
        back_populates="path",
        cascade="save-update, merge",
    )

    __table_args__ = (
        CheckConstraint("status IN ('draft', 'published', 'archived')", name="ck_learning_path_status"),
        CheckConstraint("sequencing_mode IN ('linear', 'open')", name="ck_learning_path_sequencing_mode"),
        UniqueConstraint("tenant_id", "family_id", "version", name="uq_learning_path_family_version"),
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


class LearningPathAssignment(Base):
    """A durable, tenant-scoped assignment of one published program version."""

    __tablename__ = "learning_path_assignments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    path_id = Column(
        UUID(as_uuid=True), ForeignKey("learning_paths.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source = Column(Text, nullable=False, default="manual", server_default="manual")
    source_ref_id = Column(UUID(as_uuid=True), nullable=True)
    assigned_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    starts_at = Column(DateTime(timezone=True), nullable=True)
    due_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(Text, nullable=False, default="active", server_default="active")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    cancelled_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    path = relationship("LearningPath", back_populates="assignments")
    user = relationship("User", foreign_keys=[user_id])

    __table_args__ = (
        CheckConstraint(
            "source IN ('manual', 'cohort', 'department', 'position')",
            name="ck_learning_path_assignment_source",
        ),
        CheckConstraint(
            "status IN ('active', 'cancelled', 'completed')",
            name="ck_learning_path_assignment_status",
        ),
        UniqueConstraint("path_id", "user_id", name="uq_learning_path_assignment_path_user"),
    )
