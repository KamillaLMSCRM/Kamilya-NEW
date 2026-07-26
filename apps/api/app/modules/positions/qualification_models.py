"""Immutable qualification-card snapshots for positions."""

import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.db import Base


class PositionQualificationVersion(Base):
    """Full immutable snapshot of a position's qualification card."""

    __tablename__ = "position_qualification_versions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "position_id",
            "version_no",
            name="uq_position_qualification_version",
        ),
        Index(
            "ix_position_qualification_versions_tenant_position_version",
            "tenant_id",
            "position_id",
            "version_no",
        ),
        Index(
            "ix_position_qualification_versions_tenant_position_created",
            "tenant_id",
            "position_id",
            "created_at",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid())
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    position_id = Column(
        UUID(as_uuid=True),
        ForeignKey("positions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_no = Column(Integer, nullable=False)
    snapshot = Column(JSONB, nullable=False)
    change_kind = Column(String(64), nullable=False)
    change_reason = Column(Text, nullable=True)
    created_by = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
