from uuid import uuid4
from sqlalchemy import Column, Text, Integer, CheckConstraint, TIMESTAMP, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.core.db import Base
import re


class TenantSettings(Base):
    __tablename__ = "tenant_settings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    logo_url = Column(Text, nullable=True)
    primary_color = Column(Text, nullable=True)
    default_language = Column(Text, nullable=False, default="ru")
    self_enrollment = Column(Text, nullable=False, default="false")
    quiz_pass_threshold = Column(Text, nullable=False, default="80")
    # Per-tenant monthly LLM budget in USD cents (audit §6.3).
    # Default 5000 = $50/month. Set to 0 to disable the gate entirely
    # (call sites will skip the check when this is 0).
    # Override per-tenant via UPDATE tenant_settings SET monthly_llm_budget_usd_cents = X.
    monthly_llm_budget_usd_cents = Column(Integer, nullable=False, default=5000)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint("default_language IN ('ru', 'kk', 'en')", name="ck_tenant_lang"),
        CheckConstraint("monthly_llm_budget_usd_cents >= 0", name="ck_tenant_llm_budget_nonneg"),
    )
