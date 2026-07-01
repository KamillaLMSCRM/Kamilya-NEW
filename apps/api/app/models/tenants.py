from uuid import uuid4
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, Text, TIMESTAMP, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.core.db import Base


class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(Text, nullable=False)
    slug = Column(Text, nullable=False, unique=True, index=True)
    status = Column(Text, nullable=False, default="trial")
    plan = Column(Text, nullable=False, default="free")
    trial_started_at = Column(DateTime(timezone=True), nullable=True)
    trial_ends_at = Column(DateTime(timezone=True), nullable=True)
    paid_until = Column(DateTime(timezone=True), nullable=True)
    max_users = Column(Integer, nullable=True)
    max_courses_per_month = Column(Integer, nullable=True)
    billing_contact_email = Column(Text, nullable=True)
    billing_company_name = Column(Text, nullable=True)
    billing_identifier = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    settings = Column(JSONB, nullable=False, default=dict)
    # Prospect sandbox flag — see app/core/demo_limits.py for the
    # per-resource caps that are enforced when this is true.
    is_demo = Column(Boolean, nullable=False, server_default="false", default=False)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class TenantLead(Base):
    __tablename__ = "tenant_leads"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True, index=True)
    company_name = Column(Text, nullable=False)
    contact_name = Column(Text, nullable=False)
    email = Column(Text, nullable=False, index=True)
    phone = Column(Text, nullable=True)
    telegram_username = Column(Text, nullable=True)
    employee_count_range = Column(Text, nullable=True)
    preferred_language = Column(Text, nullable=False, default="ru")
    intent = Column(Text, nullable=False, default="try")
    status = Column(Text, nullable=False, default="lead_submitted")
    source = Column(Text, nullable=False, default="landing")
    message = Column(Text, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class TenantUsage(Base):
    __tablename__ = "tenant_usage"

    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    ai_course_generations_used = Column(Integer, nullable=False, default=0, server_default="0")
    jd_course_generations_used = Column(Integer, nullable=False, default=0, server_default="0")
    active_students_count_snapshot = Column(Integer, nullable=False, default=0, server_default="0")
    system_users_count_snapshot = Column(Integer, nullable=False, default=0, server_default="0")
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
