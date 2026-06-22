"""Document model"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, BigInteger, Text, DateTime
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
    size = Column("file_size", BigInteger, nullable=False, server_default="0")
    s3_key = Column(String, nullable=False, server_default="")
    description = Column(Text, nullable=False, server_default="")
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
