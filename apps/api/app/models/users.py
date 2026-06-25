from uuid import uuid4
from sqlalchemy import Column, Text, BigInteger, Boolean, TIMESTAMP, DateTime, CheckConstraint, Index, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from app.core.db import Base

# Force positions table to be loaded before User resolves ForeignKey("positions.id")
from app.modules.positions.models import Position, PositionCourse  # noqa: F401


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    email = Column(Text, index=True, nullable=True)
    personnel_number = Column(Text, nullable=True, index=True)  # табельный/employee ID (optional, unique per tenant)
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
        Index("uq_users_tenant_personnel", "tenant_id", "personnel_number", unique=True, postgresql_where="personnel_number IS NOT NULL"),
        {"extend_existing": True},
    )


class UserInvitation(Base):
    """Pending invitation token for a future user.

    Lifecycle:
      1. Methodologist/admin POSTs /users/invitations/bulk with email list
      2. New row created: status='pending', token generated, expires_at = now + tenant.invite_expiry_days
      3. Methodologist copies invite URL, sends manually via Slack/Telegram/etc.
      4. User clicks link → /accept-invite?token=... → POST /invitations/{token}/accept with password
      5. On accept: user.password_hash set, is_active=true, status='active';
         invitation.status='accepted', accepted_at=now, user_id set
      6. If user doesn't accept in time: status='expired' (background sweep or on-access)
      7. If methodologist re-invites: old row status='superseded', new row created

    Only one PENDING row per (tenant_id, email) — enforced by partial unique index in migration.
    """
    __tablename__ = "user_invitations"
    __table_args__ = {"extend_existing": True}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4, server_default=func.gen_random_uuid())
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    email = Column(Text, nullable=False)
    first_name = Column(Text, nullable=False, default="")
    last_name = Column(Text, nullable=False, default="")
    personnel_number = Column(Text, nullable=True)  # if HR has it, used as soft 2FA at accept time
    role = Column(Text, nullable=False, default="student")
    invited_by = Column(UUID(as_uuid=True), nullable=False)  # FK users (no FK declared — circular import)
    token = Column(Text, nullable=False, unique=True)
    status = Column(
        Text, nullable=False, default="pending",
        # pending | accepted | expired | revoked | superseded
    )
    expires_at = Column(DateTime(timezone=True), nullable=False)
    accepted_at = Column(DateTime(timezone=True), nullable=True)
    superseded_by = Column(UUID(as_uuid=True), nullable=True)  # FK to UserInvitation.id (set when superseded)
    user_id = Column(UUID(as_uuid=True), nullable=True)  # FK users (set on accept)
    # Audit fields (Stage 1a patch)
    accepted_ip = Column(Text, nullable=True)  # IP of accept request — for HR audit if magic link leaked
    accepted_user_agent = Column(Text, nullable=True)  # UA of accept request
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
