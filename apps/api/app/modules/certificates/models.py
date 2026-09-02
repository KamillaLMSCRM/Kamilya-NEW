"""Certificate model"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, Column, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID

from app.core.db import Base


class Certificate(Base):
    __tablename__ = "certificates"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    course_id = Column(UUID(as_uuid=True), ForeignKey("courses.id", ondelete="cascade"), nullable=False, index=True)
    enrollment_id = Column(
        UUID(as_uuid=True), ForeignKey("enrollments.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    learning_path_assignment_id = Column(
        UUID(as_uuid=True),
        ForeignKey("learning_path_assignments.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    certificate_number = Column(String(50), nullable=False, unique=True)
    issued_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    expires_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    revoked_reason = Column(Text, nullable=True)
    template_version = Column(String(20), nullable=False, default="v3", server_default="v3")
    pdf_sha256 = Column(String(64), nullable=True)
    pdf_path = Column(Text, nullable=True)
    metadata_ = Column("metadata", JSON, nullable=True)

    @property
    def status(self) -> str:
        if self.revoked_at is not None:
            return "revoked"
        now = datetime.now(UTC)
        expires_at = self.expires_at
        if expires_at is not None:
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            if expires_at <= now:
                return "expired"
        return "active"

    @property
    def user_name(self) -> str:
        return str((self.metadata_ or {}).get("user_name", ""))

    @property
    def course_title(self) -> str:
        return str((self.metadata_ or {}).get("course_title", ""))
