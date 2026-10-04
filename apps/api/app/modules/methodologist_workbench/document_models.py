"""One immutable source-bound workflow context, linked to one admitted AI job."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, FetchedValue, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class DocumentPlan(Base):
    __tablename__ = "workbench_document_plans"
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"))
    actor_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True))
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    status: Mapped[str] = mapped_column(String(16), default="ready", nullable=False)
    job_id: Mapped[str | None] = mapped_column(String, ForeignKey("ai_jobs.id"))
    admitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_onupdate=FetchedValue())

    __table_args__ = (
        CheckConstraint("(status='ready' AND job_id IS NULL AND admitted_at IS NULL) OR "
                        "(status='submitted' AND job_id IS NOT NULL AND admitted_at IS NOT NULL)",
                        name="ck_workbench_document_state"),
        Index("uq_workbench_document_job", "job_id", unique=True),
        Index("ix_workbench_document_owner", "tenant_id", "actor_id", "created_at"),
    )
