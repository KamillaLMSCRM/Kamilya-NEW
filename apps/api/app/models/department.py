"""Department — normalized org-chart node (ADR-0011).

The physical ``departments`` table is retained for compatibility while the
organization-unit module adds explicit branch/department semantics.
"""

import uuid

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.db import Base


def _legacy_source_metadata() -> dict[str, str]:
    return {"origin": "legacy_adapter"}


class Department(Base):
    __tablename__ = "departments"
    __table_args__ = (
        # Kept while legacy clients still resolve a department by tenant-wide
        # slug. Canonical child slugs include parent scope.
        UniqueConstraint("tenant_id", "slug", name="uq_departments_tenant_slug"),
        Index("idx_departments_tenant", "tenant_id"),
        {"extend_existing": True},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    name = Column(Text, nullable=False)
    slug = Column(Text, nullable=False)

    unit_type = Column(Text, nullable=False, default="department")
    normalized_name = Column(Text, nullable=False, default="")
    external_key = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    archived_at = Column(DateTime(timezone=True), nullable=True)
    source_metadata = Column(
        JSONB,
        nullable=False,
        default=_legacy_source_metadata,
        server_default='{"origin":"legacy_adapter"}',
    )
    # Existing flat rows may remain root departments until a tenant-specific
    # approved import classifies them. Canonical writes set this to false.
    legacy_root = Column(Boolean, nullable=False, default=True)

    description = Column(Text, nullable=False, default="")
    code = Column(Text, nullable=True)
    head_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    parent_id = Column(
        UUID(as_uuid=True),
        ForeignKey("departments.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
