"""ORM declarations for durable, pre-course AI generation state."""

from datetime import UTC, datetime

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.db import Base


class AIGenerationRun(Base):
    __tablename__ = "ai_generation_runs"

    id = Column(UUID(as_uuid=True), primary_key=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    generation_key = Column(String(160), nullable=False)
    plan_revision = Column(String(160), nullable=False)
    source_job_id = Column(String(255), nullable=False)
    plan_payload = Column(JSONB, nullable=False)
    lease_owner = Column(String(160), nullable=True)
    lease_expires_at = Column(DateTime(timezone=True), nullable=True)
    lease_duration_seconds = Column(Integer, nullable=False, default=300)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    __table_args__ = (
        UniqueConstraint("tenant_id", "generation_key", name="uq_ai_generation_runs_tenant_generation"),
        UniqueConstraint("tenant_id", "id", name="uq_ai_generation_runs_tenant_id"),
        ForeignKeyConstraint(
            ("tenant_id", "source_job_id"),
            ("ai_jobs.tenant_id", "ai_jobs.id"),
            name="fk_ai_generation_runs_tenant_job",
            ondelete="RESTRICT",
        ),
        CheckConstraint("lease_duration_seconds BETWEEN 1 AND 900", name="ck_ai_generation_runs_lease_duration"),
    )


class AIGenerationLessonCheckpoint(Base):
    __tablename__ = "ai_generation_lesson_checkpoints"

    id = Column(UUID(as_uuid=True), primary_key=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    generation_run_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    module_key = Column(String(160), nullable=False)
    lesson_key = Column(String(160), nullable=False)
    module_order = Column(Integer, nullable=False)
    lesson_order = Column(Integer, nullable=False)
    content_status = Column(String(16), nullable=False, default="pending")
    review_status = Column(String(16), nullable=False, default="pending")
    assessment_status = Column(String(16), nullable=False, default="pending")
    content_payload = Column(JSONB, nullable=True)
    review_payload = Column(JSONB, nullable=True)
    assessment_payload = Column(JSONB, nullable=True)
    lease_owner = Column(String(160), nullable=True)
    lease_expires_at = Column(DateTime(timezone=True), nullable=True)
    lease_duration_seconds = Column(Integer, nullable=False, default=300)
    attempt_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "generation_run_id", "module_key", "lesson_key",
            name="uq_ai_generation_lesson_identity",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "generation_run_id"),
            ("ai_generation_runs.tenant_id", "ai_generation_runs.id"),
            name="fk_ai_generation_checkpoint_tenant_run",
            ondelete="CASCADE",
        ),
        CheckConstraint("lease_duration_seconds BETWEEN 1 AND 900", name="ck_ai_generation_checkpoint_lease_duration"),
        CheckConstraint("attempt_count >= 0", name="ck_ai_generation_checkpoint_attempt_count"),
    )
