"""Document model"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, BigInteger, Text, DateTime, TIMESTAMP, func
from sqlalchemy.dialects.postgresql import UUID
from app.core.db import Base


class Document(Base):
    __tablename__ = "documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    uploaded_by = Column(UUID(as_uuid=True), nullable=False, index=True)
    title = Column(String, nullable=False)
    filename = Column(String, nullable=False, server_default="unknown")
    content_type = Column(String, nullable=False)
    file_url = Column(Text, nullable=True)
    size = Column("file_size", BigInteger, nullable=False, default=0)
    s3_key = Column(String, nullable=False, server_default="")
    description = Column(Text, nullable=False, server_default="")
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
