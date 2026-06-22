import uuid
from sqlalchemy import Column, Text, UUID, DateTime, Integer, func
from app.core.db import Base


class Position(Base):
    __tablename__ = "positions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    name = Column(Text, nullable=False)
    department = Column(Text, nullable=False, default="")
    level = Column(Text, nullable=False, default="")
    employee_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
