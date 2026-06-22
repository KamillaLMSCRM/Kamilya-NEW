"""Position model for users.position_id FK"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, Text, TIMESTAMP, func
from sqlalchemy.dialects.postgresql import UUID
from app.core.db import Base


class Position(Base):
    """Positions table — created by alembic 0010/0011, referenced by users.position_id."""
    __tablename__ = "positions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    name = Column(String, nullable=False)
    department = Column(String, nullable=False, server_default="")
    level = Column(String, nullable=False, server_default="")
    responsibilities = Column(Text, nullable=False, server_default="")
    requirements = Column(Text, nullable=False, server_default="")
    course_id = Column(UUID(as_uuid=True), nullable=True)
    employee_count = Column(Integer, nullable=False, default=0)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
