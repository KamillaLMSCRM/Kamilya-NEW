from sqlalchemy import Column, Text, BigInteger, TIMESTAMP, DateTime, CheckConstraint, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from app.core.db import Base


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    email = Column(Text, index=True, nullable=True)
    telegram_id = Column(BigInteger, nullable=True)
    password_hash = Column(Text, nullable=True)
    first_name = Column(Text, nullable=False)
    last_name = Column(Text, nullable=False)
    status = Column(Text, nullable=False, default="active")
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint("status IN ('active', 'inactive', 'banned')", name="ck_user_status"),
        UniqueConstraint("tenant_id", "telegram_id", name="uq_user_telegram", postgresql_where="telegram_id IS NOT NULL"),
    )
