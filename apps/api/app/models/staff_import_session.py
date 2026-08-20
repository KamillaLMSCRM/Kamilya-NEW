"""Persistent audit record for adaptive staff import sessions."""

from __future__ import annotations

import uuid

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.db import Base


class StaffImportSession(Base):
    __tablename__ = "staff_import_sessions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_staff_import_sessions_tenant_idempotency",
        ),
        Index("ix_staff_import_sessions_tenant_created", "tenant_id", "created_at"),
        Index("ix_staff_import_sessions_tenant_state", "tenant_id", "state"),
        {"extend_existing": True},
    )

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    actor_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    mapping_id = Column(
        UUID(as_uuid=True),
        ForeignKey("staff_import_mappings.id", ondelete="SET NULL"),
        nullable=True,
    )
    actor_role = Column(Text, nullable=False)
    state = Column(Text, nullable=False, default="uploaded", server_default="uploaded")
    mode = Column(Text, nullable=False, default="ADD_OR_UPDATE", server_default="ADD_OR_UPDATE")
    idempotency_key = Column(Text, nullable=False)

    source_file_name = Column(Text, nullable=False)
    source_file_sha256 = Column(Text, nullable=False)
    source_format = Column(Text, nullable=False)
    source_size_bytes = Column(Integer, nullable=False)
    source_object_key = Column(Text, nullable=True)
    parser_version = Column(Text, nullable=False)

    workbook_analysis = Column(JSONB, nullable=True)
    mapping_json = Column(JSONB, nullable=True)
    proposal_json = Column(JSONB, nullable=True)
    proposal_revision = Column(Text, nullable=True)
    proposal_hash = Column(Text, nullable=True)
    reviewed_revision = Column(Text, nullable=True)
    approved_revision = Column(Text, nullable=True)
    approval_token_hash = Column(Text, nullable=True)
    full_reconciliation_confirmation = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default=func.false(),
    )
    result_summary = Column(JSONB, nullable=True)
    error_code = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    version = Column(Integer, nullable=False, default=1, server_default="1")

    expires_at = Column(DateTime(timezone=True), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    committed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class StaffImportSessionEvent(Base):
    __tablename__ = "staff_import_session_events"
    __table_args__ = (
        Index("ix_staff_import_session_events_session_created", "session_id", "created_at"),
        Index("ix_staff_import_session_events_tenant_created", "tenant_id", "created_at"),
        {"extend_existing": True},
    )

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    session_id = Column(
        UUID(as_uuid=True),
        ForeignKey("staff_import_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    actor_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    from_state = Column(Text, nullable=True)
    to_state = Column(Text, nullable=False)
    event_type = Column(Text, nullable=False)
    reason = Column(Text, nullable=True)
    event_metadata = Column(JSONB, nullable=False, default=dict, server_default=func.text("'{}'::jsonb"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
