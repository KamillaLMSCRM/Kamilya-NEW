"""Database models for immutable training procedure evidence.

The existing ContentRelease and QuizAttempt evidence remain the source of
truth for course versions and attempts. These rows only record the procedure
performed around that material and link back to those immutable objects.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, ForeignKey, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.db import Base


class TrainingEvidenceEvent(Base):
    __tablename__ = "training_evidence_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    enrollment_id = Column(
        UUID(as_uuid=True),
        ForeignKey("enrollments.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    content_release_id = Column(
        UUID(as_uuid=True),
        ForeignKey("content_releases.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    procedure_type = Column(Text, nullable=False, index=True)
    # Populated only by trusted workflow integrations. Nullable keeps the
    # append-only correction/revocation records and existing internal callers
    # compatible; workflow events always provide this key.
    source_event_key = Column(Text, nullable=True)
    record_type = Column(Text, nullable=False, default="original", server_default="original")
    related_event_id = Column(
        UUID(as_uuid=True),
        ForeignKey("training_evidence_events.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    reason = Column(Text, nullable=True)
    payload_snapshot = Column(JSONB, nullable=False)
    payload_sha256 = Column(Text, nullable=False)
    recorded_by_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    occurred_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default="now()")

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "source_event_key",
            name="uq_training_evidence_events_tenant_source_key",
        ),
    )


class TrainingEvidenceStepUpConfirmation(Base):
    __tablename__ = "training_evidence_step_up_confirmations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True)
    event_id = Column(
        UUID(as_uuid=True),
        ForeignKey("training_evidence_events.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    action_text = Column(Text, nullable=False)
    object_version = Column(Text, nullable=False)
    reauth_method = Column(Text, nullable=False)
    confirmed_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
    ip_address = Column(Text, nullable=True)
    user_agent = Column(Text, nullable=True)
    confirmation_sha256 = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default="now()")

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "event_id",
            "user_id",
            name="uq_training_evidence_confirmation_subject",
        ),
    )


class TrainingEvidenceLegalHold(Base):
    __tablename__ = "training_evidence_legal_holds"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True)
    event_id = Column(
        UUID(as_uuid=True),
        ForeignKey("training_evidence_events.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    action = Column(Text, nullable=False)
    reason = Column(Text, nullable=False)
    acted_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    occurred_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
    payload_sha256 = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default="now()")
