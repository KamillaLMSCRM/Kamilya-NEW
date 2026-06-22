from sqlalchemy import Column, Text, BigInteger, Boolean, TIMESTAMP, DateTime, CheckConstraint, Index, ForeignKey, func
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
    role = Column(Text, nullable=False, default="student")
    is_active = Column(Boolean, nullable=False, default=True)
    position_id = Column(UUID(as_uuid=True), ForeignKey("positions.id", ondelete="SET NULL"), nullable=True)
    last_login = Column(DateTime(timezone=True), nullable=True)
    status = Column(Text, nullable=False, default="active")
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    @property
    def roles(self) -> list[str]:
        return [self.role]

    __table_args__ = (
        CheckConstraint("status IN ('active', 'inactive', 'banned')", name="ck_user_status"),
        CheckConstraint("role IN ('superadmin', 'admin', 'org_admin', 'teacher', 'student')", name="ck_user_role"),
        Index("uq_user_telegram", "tenant_id", "telegram_id", unique=True, postgresql_where="telegram_id IS NOT NULL"),
        {"extend_existing": True},
    )
