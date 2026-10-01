"""Immutable server-owned preview and its atomic committed receipt."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, FetchedValue, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class AssignmentPlan(Base):
    __tablename__ = "workbench_assignment_plans"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"))
    actor_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True))
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    preview: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="ready", nullable=False)
    receipt: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_onupdate=FetchedValue())

    __table_args__ = (
        CheckConstraint("status IN ('ready','succeeded')", name="ck_workbench_plan_status"),
        CheckConstraint(
            "(status='ready' AND receipt IS NULL) OR (status='succeeded' AND receipt IS NOT NULL)",
            name="ck_workbench_plan_receipt",
        ),
        CheckConstraint("status='succeeded' OR executed_at IS NULL", name="ck_workbench_plan_execution_time"),
        Index("ix_workbench_plan_owner_created", "tenant_id", "actor_id", "created_at"),
    )
