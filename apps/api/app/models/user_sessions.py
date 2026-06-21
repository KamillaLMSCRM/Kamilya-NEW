from sqlalchemy import Column, Text, TIMESTAMP, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from app.core.db import Base


class UserSession(Base):
    __tablename__ = "user_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True, ForeignKey("users.id", ondelete="CASCADE"))
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True, ForeignKey("tenants.id", ondelete="CASCADE"))
    refresh_token = Column(Text, nullable=False, index=True)
    expires_at = Column(TIMESTAMP(timezone=True), nullable=False)
    user_agent = Column(Text, nullable=True)
    ip_address = Column(Text, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("refresh_token", name="uq_session_refresh_token"),
    )
