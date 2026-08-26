"""Persistence for tenant Staff Sync credentials, identities and events."""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.db import Base


class StaffSyncCredential(Base):
    __tablename__ = "staff_sync_credentials"
    __table_args__ = (
        Index("ix_staff_sync_credentials_tenant", "tenant_id"),
        {"extend_existing": True},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid())
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    name = Column(Text, nullable=False)
    token_hash = Column(String(64), nullable=False, unique=True)
    scopes = Column(JSONB, nullable=False, default=lambda: ["staff:sync"], server_default='["staff:sync"]')
    is_active = Column(Boolean, nullable=False, default=True, server_default=func.true())
    expires_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class StaffSyncIdentity(Base):
    __tablename__ = "staff_sync_identities"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "source", "external_employee_id",
            name="uq_staff_sync_external_identity",
        ),
        UniqueConstraint(
            "tenant_id", "source", "user_id",
            name="uq_staff_sync_user_source",
        ),
        Index("ix_staff_sync_identities_user", "tenant_id", "user_id"),
        {"extend_existing": True},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid())
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    source = Column(String(80), nullable=False)
    external_employee_id = Column(String(200), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class StaffSyncEvent(Base):
    __tablename__ = "staff_sync_events"
    __table_args__ = (
        UniqueConstraint("tenant_id", "source", "event_id", name="uq_staff_sync_event"),
        Index("ix_staff_sync_events_tenant_created", "tenant_id", "created_at"),
        Index("ix_staff_sync_events_employee", "tenant_id", "employee_id"),
        {"extend_existing": True},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid())
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    credential_id = Column(
        UUID(as_uuid=True),
        ForeignKey("staff_sync_credentials.id", ondelete="RESTRICT"),
        nullable=False,
    )
    source = Column(String(80), nullable=False)
    event_id = Column(String(200), nullable=False)
    payload_sha256 = Column(String(64), nullable=False)
    action = Column(String(24), nullable=False)
    external_employee_id = Column(String(200), nullable=False)
    status = Column(String(32), nullable=False, default="processing", server_default="processing")
    employee_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    effective_at = Column(DateTime(timezone=True), nullable=False)
    outcome_json = Column(JSONB, nullable=False, default=dict, server_default="{}")
    processed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
