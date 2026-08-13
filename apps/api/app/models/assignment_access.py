"""Per-learner, second-factor protected access credentials."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, Text
from sqlalchemy.dialects.postgresql import UUID

from app.core.db import Base


class AssignmentAccessCredential(Base):
    __tablename__ = "assignment_access_credentials"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    enrollment_id = Column(UUID(as_uuid=True), ForeignKey("enrollments.id", ondelete="RESTRICT"), nullable=False)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    token_hash = Column(Text, nullable=False, unique=True)
    pin_hash = Column(Text, nullable=False)
    # ``expires_at`` limits only the one-time public link/PIN exchange.  A
    # bearer token issued after that exchange is bounded by its JWT lifetime
    # and the enrollment policy, not by the link's expiry.
    expires_at = Column(DateTime(timezone=True), nullable=False)
    first_exchanged_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    revoked_reason = Column(Text, nullable=True)
    failed_attempts = Column(Integer, nullable=False, default=0, server_default="0")
    locked_until = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))

    __table_args__ = (
        Index(
            "uq_assignment_access_active_enrollment",
            "enrollment_id",
            unique=True,
            postgresql_where=revoked_at.is_(None),
        ),
    )
