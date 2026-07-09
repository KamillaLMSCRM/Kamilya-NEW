"""KioskLink model — Stage 1b of employee onboarding epic.

A kiosk link is a single shareable URL that workers access at a shared device
(workshop kiosk, tablet at break room). HR prints the URL as a QR code or
posts it on the wall. Workers identify themselves by personnel_number (or
in future versions: select from name list / scan badge).

One kiosk link = one URL. If HR wants multiple kiosks (e.g., per workshop),
they create multiple links.
"""
from uuid import uuid4
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from app.core.db import Base


class KioskLink(Base):
    __tablename__ = "kiosk_links"
    __table_args__ = {"extend_existing": True}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4, server_default=func.gen_random_uuid())
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    name = Column(String(255), nullable=False)  # HR-readable label
    token = Column(Text, nullable=False, unique=True)  # URL-safe token for the kiosk URL
    location = Column(Text, nullable=True)  # free text ("Цех №1, Алматы")
    scope_position_id = Column(
        UUID(as_uuid=True),
        ForeignKey("positions.id", ondelete="SET NULL"),
        nullable=True,
    )  # NULL = any active user in tenant; set = only users with this position
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    created_by = Column(UUID(as_uuid=True), nullable=False)  # FK users (no FK declared for circular import reasons)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=True)  # optional lifetime


class KioskAccessLog(Base):
    __tablename__ = "kiosk_access_logs"
    __table_args__ = {"extend_existing": True}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4, server_default=func.gen_random_uuid())
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    kiosk_id = Column(UUID(as_uuid=True), ForeignKey("kiosk_links.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    personnel_number = Column(Text, nullable=True)
    success = Column(Boolean, nullable=False, default=False, server_default="false")
    reason = Column(Text, nullable=True)
    ip_address = Column(Text, nullable=True)
    user_agent = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
