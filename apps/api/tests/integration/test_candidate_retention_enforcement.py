from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text

from app.modules.candidate_assessments.models import (
    AssessmentCandidate,
    CandidateAccessCredential,
    CandidateAssessmentAttempt,
    CandidateAssessmentCampaign,
    CandidateAssessmentRetentionAggregate,
)
from app.modules.courses.release_models import ContentRelease
from app.modules.courses.release_service import canonical_json_sha256

pytestmark = pytest.mark.asyncio


async def _seed_tenant(db, set_current_tenant, tenant, manager, course, *, overdue_offset: int):
    await set_current_tenant(tenant)
    release_snapshot = {"course": {"title": "Retention"}, "modules": []}
    release = ContentRelease(
        tenant_id=tenant.id,
        course_id=course.id,
        version=1,
        snapshot=release_snapshot,
        snapshot_sha256=canonical_json_sha256(release_snapshot),
        published_by=manager.id,
    )
    db.add(release)
    await db.flush()
    campaign = CandidateAssessmentCampaign(
        tenant_id=tenant.id,
        content_release_id=release.id,
        created_by=manager.id,
        title="Retention",
        status="active",
        expires_at=datetime.now(UTC) + timedelta(days=1),
        attempt_limit=1,
        retention_days=30,
        assessment_snapshot={"quizzes": []},
        snapshot_sha256=canonical_json_sha256({"quizzes": []}),
    )
    db.add(campaign)
    await db.flush()
    expired = AssessmentCandidate(
        tenant_id=tenant.id,
        campaign_id=campaign.id,
        first_name="Private",
        last_name="Candidate",
        email="private@example.test",
        status="completed",
        retention_until=datetime.now(UTC) - timedelta(days=overdue_offset),
    )
    future = AssessmentCandidate(
        tenant_id=tenant.id,
        campaign_id=campaign.id,
        first_name="Keep",
        last_name="Candidate",
        email="keep@example.test",
        status="active",
        retention_until=datetime.now(UTC) + timedelta(days=30),
    )
    db.add_all([expired, future])
    await db.flush()
    db.add(
        CandidateAccessCredential(
            tenant_id=tenant.id,
            campaign_id=campaign.id,
            candidate_id=expired.id,
            token_hash=uuid4().hex + uuid4().hex,
            pin_hash="argon2",
            expires_at=datetime.now(UTC) + timedelta(days=1),
        )
    )
    db.add(
        CandidateAssessmentAttempt(
            tenant_id=tenant.id,
            campaign_id=campaign.id,
            candidate_id=expired.id,
            attempt_number=1,
            status="submitted",
            assessment_snapshot={"secret": True},
            answers=[{"private": True}],
            answers_sha256="a" * 64,
            earned_points=1,
            total_points=2,
            score_percent=50,
            passed=False,
            submitted_at=datetime.now(UTC),
        )
    )
    await db.flush()
    return campaign, expired, future


async def test_overdue_retention_is_bounded_cross_tenant_and_idempotent(
    db_session, make_tenant, make_user, make_course, set_current_tenant
) -> None:
    tenant_a = await make_tenant(name="Retention A")
    tenant_b = await make_tenant(name="Retention B")
    manager_a = await make_user(tenant_a, role="methodologist")
    manager_b = await make_user(tenant_b, role="methodologist")
    course_a = await make_course(tenant_a, manager_a, status="published")
    course_b = await make_course(tenant_b, manager_b, status="published")
    campaign_a, expired_a, future_a = await _seed_tenant(
        db_session, set_current_tenant, tenant_a, manager_a, course_a, overdue_offset=2
    )
    _campaign_b, expired_b, _future_b = await _seed_tenant(
        db_session, set_current_tenant, tenant_b, manager_b, course_b, overdue_offset=1
    )

    processed = await db_session.scalar(text("SELECT enforce_expired_candidate_retention(1)"))
    assert processed == 1
    await set_current_tenant(tenant_a)
    await db_session.refresh(expired_a)
    await db_session.refresh(future_a)
    assert (expired_a.first_name, expired_a.email, expired_a.status) == ("Deleted", None, "deleted")
    assert (future_a.first_name, future_a.status) == ("Keep", "active")
    assert (
        await db_session.scalar(
            select(func.count(CandidateAssessmentAttempt.id)).where(
                CandidateAssessmentAttempt.candidate_id == expired_a.id
            )
        )
        == 0
    )
    credential = await db_session.scalar(
        select(CandidateAccessCredential).where(CandidateAccessCredential.candidate_id == expired_a.id)
    )
    assert credential is not None and credential.revoked_at is not None
    aggregate = await db_session.get(CandidateAssessmentRetentionAggregate, (tenant_a.id, campaign_a.id))
    assert aggregate is not None
    assert (aggregate.candidates_redacted, aggregate.submitted_attempts, aggregate.score_percent_sum) == (1, 1, 50)

    await set_current_tenant(tenant_b)
    await db_session.refresh(expired_b)
    assert expired_b.status == "completed"
    assert await db_session.scalar(text("SELECT enforce_expired_candidate_retention(100)")) == 1
    await db_session.refresh(expired_b)
    assert expired_b.status == "deleted"
    assert await db_session.scalar(text("SELECT enforce_expired_candidate_retention(100)")) == 0
