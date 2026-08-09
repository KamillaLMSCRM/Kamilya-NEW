from __future__ import annotations

from uuid import uuid4

from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.db import Base


class CandidateAssessmentCampaign(Base):
    __tablename__ = "candidate_assessment_campaigns"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    content_release_id = Column(
        UUID(as_uuid=True), ForeignKey("content_releases.id", ondelete="RESTRICT"), nullable=False
    )
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    title = Column(Text, nullable=False)
    instructions = Column(Text, nullable=False, default="")
    status = Column(Text, nullable=False, default="draft")
    expires_at = Column(DateTime(timezone=True), nullable=False)
    attempt_limit = Column(Integer, nullable=False, default=1)
    retention_days = Column(Integer, nullable=False, default=180)
    assessment_snapshot = Column(JSONB, nullable=False)
    snapshot_sha256 = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AssessmentCandidate(Base):
    __tablename__ = "assessment_candidates"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    campaign_id = Column(
        UUID(as_uuid=True), ForeignKey("candidate_assessment_campaigns.id", ondelete="RESTRICT"), nullable=False
    )
    first_name = Column(Text, nullable=False)
    last_name = Column(Text, nullable=False, default="")
    email = Column(Text)
    phone = Column(Text)
    status = Column(Text, nullable=False, default="invited")
    consented_at = Column(DateTime(timezone=True))
    retention_until = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class CandidateAccessCredential(Base):
    __tablename__ = "candidate_access_credentials"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    campaign_id = Column(
        UUID(as_uuid=True), ForeignKey("candidate_assessment_campaigns.id", ondelete="RESTRICT"), nullable=False
    )
    candidate_id = Column(
        UUID(as_uuid=True), ForeignKey("assessment_candidates.id", ondelete="RESTRICT"), nullable=False
    )
    token_hash = Column(String(64), nullable=False, unique=True)
    pin_hash = Column(Text, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked_at = Column(DateTime(timezone=True))
    failed_attempts = Column(Integer, nullable=False, default=0)
    locked_until = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class CandidateAssessmentAttempt(Base):
    __tablename__ = "candidate_assessment_attempts"
    __table_args__ = (
        UniqueConstraint("candidate_id", "campaign_id", "attempt_number", name="uq_candidate_campaign_attempt_number"),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    campaign_id = Column(
        UUID(as_uuid=True), ForeignKey("candidate_assessment_campaigns.id", ondelete="RESTRICT"), nullable=False
    )
    candidate_id = Column(
        UUID(as_uuid=True), ForeignKey("assessment_candidates.id", ondelete="RESTRICT"), nullable=False
    )
    attempt_number = Column(Integer, nullable=False)
    status = Column(Text, nullable=False, default="started")
    assessment_snapshot = Column(JSONB, nullable=False)
    answers = Column(JSONB, nullable=False, default=list)
    answers_sha256 = Column(String(64))
    earned_points = Column(Integer)
    total_points = Column(Integer)
    score_percent = Column(Integer)
    passed = Column(Boolean)
    started_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    submitted_at = Column(DateTime(timezone=True))


class CandidateAssessmentRetentionAggregate(Base):
    __tablename__ = "candidate_assessment_retention_aggregates"
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    campaign_id = Column(
        UUID(as_uuid=True), ForeignKey("candidate_assessment_campaigns.id", ondelete="RESTRICT"), primary_key=True
    )
    candidates_redacted = Column(Integer, nullable=False, default=0)
    submitted_attempts = Column(Integer, nullable=False, default=0)
    passed_attempts = Column(Integer, nullable=False, default=0)
    score_percent_sum = Column(BigInteger, nullable=False, default=0)
    last_enforced_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
