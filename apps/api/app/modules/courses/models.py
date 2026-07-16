from uuid import uuid4
from sqlalchemy import Column, Text, UUID, DateTime, Boolean, ForeignKey, func, CheckConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import JSONB
from app.core.db import Base
from app.models.document import Document  # noqa: F401 - registers source FK target

class Course(Base):
    __tablename__ = "courses"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    title = Column(Text, nullable=False)
    description = Column(Text, nullable=False, default="")
    status = Column(Text, nullable=False, default="draft")
    delivery_type = Column(Text, nullable=False, default="native")
    thumbnail_url = Column(Text, nullable=True)
    created_by = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    published_at = Column(DateTime(timezone=True), nullable=True)
    ai_generated = Column(Boolean, nullable=False, default=False)
    source_instruction_id = Column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_instruction_version_at = Column(DateTime(timezone=True), nullable=True)

    # Review / approval workflow (methodologist sign-off).
    # See alembic 0027_add_course_review_fields.py for the migration.
    review_status = Column(Text, nullable=False, default="pending")
    reviewed_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    review_comment = Column(Text, nullable=True)

    modules = relationship("Module", back_populates="course", cascade="all, delete-orphan", order_by="Module.order_index")

    __table_args__ = (
        CheckConstraint("status IN ('draft', 'published', 'archived')", name="ck_course_status"),
        CheckConstraint("delivery_type IN ('native', 'scorm')", name="ck_course_delivery_type"),
        CheckConstraint("review_status IN ('pending', 'approved', 'needs_changes')", name="ck_course_review_status"),
    )
