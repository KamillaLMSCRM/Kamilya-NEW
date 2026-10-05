"""Owned proposal admission and immutable preview; never an apply receipt."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, FetchedValue, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class LessonCorrectionPlan(Base):
    __tablename__ = "workbench_lesson_correction_plans"
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"))
    actor_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True))
    request_key: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True))
    request_digest: Mapped[str] = mapped_column(String(64))
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    proposal: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_onupdate=FetchedValue())
    __table_args__ = (
        UniqueConstraint("tenant_id", "actor_id", "request_key", name="uq_lesson_correction_request"),
        Index("ix_lesson_correction_owner", "tenant_id", "actor_id", "created_at"),
    )


class LessonCorrectionApplication(Base):
    """Immutable application digests; the reviewed text stays in the parent."""

    __tablename__ = "workbench_lesson_correction_applications"
    plan_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workbench_lesson_correction_plans.id", ondelete="CASCADE"), primary_key=True
    )
    tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"))
    actor_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True))
    course_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True))
    lesson_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True))
    revision: Mapped[int] = mapped_column()
    fingerprint: Mapped[str] = mapped_column(String(64))
    before_sha256: Mapped[str] = mapped_column(String(64))
    after_sha256: Mapped[str] = mapped_column(String(64))
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LessonCorrectionAccounting(Base):
    """Durable estimate and pre-provider boundary, not actual provider billing."""

    __tablename__ = "workbench_lesson_correction_accounting"
    plan_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workbench_lesson_correction_plans.id", ondelete="CASCADE"), primary_key=True
    )
    tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"))
    actor_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True))
    month_key: Mapped[str] = mapped_column(String(7))
    estimated_cost_cents: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    provider_boundary_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_onupdate=FetchedValue())
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_onupdate=FetchedValue())
