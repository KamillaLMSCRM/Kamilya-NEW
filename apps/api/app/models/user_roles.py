from uuid import uuid4
from sqlalchemy import Column, Text, TIMESTAMP, DateTime, CheckConstraint, UniqueConstraint, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.core.db import Base


class UserRole(Base):
    __tablename__ = "user_roles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(Text, nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint("role IN ('superadmin', 'admin', 'org_admin', 'methodologist', 'teacher', 'student')", name="ck_user_role_role"),
        UniqueConstraint("user_id", "tenant_id", "role", name="uq_user_role"),
    )
