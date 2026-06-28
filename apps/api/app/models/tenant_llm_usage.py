"""TenantLLMUsage — per-tenant monthly LLM cost tracking (audit §6.3)."""
import uuid
from datetime import datetime
from sqlalchemy import Column, DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from app.core.db import Base


class TenantLLMUsage(Base):
    __tablename__ = "tenant_llm_usage"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    # Calendar month in UTC, formatted 'YYYY-MM'. Lets us reset on
    # the 1st of each month without a cron job — just check current
    # month vs the row's month.
    month_key = Column(String(7), nullable=False)
    # Cumulative cost in USD cents. Incremented optimistically before
    # LLM calls, decremented on failure (see budget.py).
    cost_cents = Column(Integer, nullable=False, default=0)
    request_count = Column(Integer, nullable=False, default=0)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        # One row per (tenant, month) — atomic INSERT ON CONFLICT uses this.
        UniqueConstraint("tenant_id", "month_key", name="uq_tenant_llm_usage_tenant_month"),
        {"extend_existing": True},
    )