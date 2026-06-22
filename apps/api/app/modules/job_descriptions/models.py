import uuid
from sqlalchemy import Column, Text, UUID, DateTime, func
from app.core.db import Base


class JobDescription(Base):
    __tablename__ = "job_descriptions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    title = Column(Text, nullable=False)
    department = Column(Text, nullable=False, default="")
    position = Column(Text, nullable=False, default="")
    description = Column(Text, nullable=False, default="")
    requirements = Column(Text, nullable=False, default="")
    status = Column(Text, nullable=False, default="active")
    course_id = Column(UUID(as_uuid=True), nullable=True)
    created_by = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
