from uuid import uuid4
from sqlalchemy import Column, Text, Integer, Boolean, TIMESTAMP, ForeignKey, func
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
from app.core.db import Base


class Module(Base):
    __tablename__ = "modules"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    course_id = Column(UUID(as_uuid=True), ForeignKey("courses.id"), nullable=False, index=True)
    title = Column(Text, nullable=False)
    description = Column(Text, nullable=False, default="")
    order_index = Column(Integer, nullable=False, default=0)
    ai_generated = Column(Boolean, nullable=False, default=False)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    course = relationship("Course", back_populates="modules")
    lessons = relationship("Lesson", back_populates="module", cascade="all, delete-orphan", order_by="Lesson.order_index")


class Lesson(Base):
    __tablename__ = "lessons"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    module_id = Column(UUID(as_uuid=True), ForeignKey("modules.id"), nullable=False, index=True)
    title = Column(Text, nullable=False)
    content_type = Column(Text, nullable=False, default="text")
    content = Column(Text, nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    order_index = Column(Integer, nullable=False, default=0)
    ai_generated = Column(Boolean, nullable=False, default=False)
    published_at = Column(TIMESTAMP(timezone=True), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    module = relationship("Module", back_populates="lessons")


class ContentBlock(Base):
    __tablename__ = "content_blocks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    lesson_id = Column(UUID(as_uuid=True), ForeignKey("lessons.id"), nullable=False, index=True)
    block_type = Column(Text, nullable=False)
    content = Column(Text, nullable=True)
    order_index = Column(Integer, nullable=False, default=0)
    metadata_ = Column("metadata", Text, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
