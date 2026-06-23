from uuid import uuid4
from sqlalchemy import Column, Text, Integer, TIMESTAMP, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.core.db import Base


class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(Text, nullable=False)
    slug = Column(Text, nullable=False, unique=True, index=True)
    status = Column(Text, nullable=False, default="trial")
    plan = Column(Text, nullable=False, default="free")
    settings = Column(JSONB, nullable=False, default=dict)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
