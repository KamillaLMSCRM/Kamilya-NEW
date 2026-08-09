"""Database ownership guards for manager-feedback domains.

These tests intentionally attempt same-context rows that reference objects
owned by another tenant.  RLS checks the new row's tenant; the relationship
triggers must independently reject the foreign relationship.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.exc import DBAPIError

from app.models.assignment_access import AssignmentAccessCredential
from app.models.enrollment import Enrollment
from app.models.user_roles import UserRole
from app.modules.candidate_assessments.models import (
    AssessmentCandidate,
    CandidateAccessCredential,
    CandidateAssessmentAttempt,
    CandidateAssessmentCampaign,
)
from app.modules.courses.release_models import ContentRelease

pytestmark = pytest.mark.asyncio


async def _expect_relationship_rejection(db_session, row) -> None:
    with pytest.raises(DBAPIError, match="mismatch"):
        async with db_session.begin_nested():
            db_session.add(row)
            await db_session.flush()


async def test_assignment_access_rejects_cross_tenant_enrollment_relationship(
    db_session,
    make_tenant,
    make_user,
    make_course,
    set_current_tenant,
) -> None:
    tenant_a = await make_tenant(name="Access owner")
    tenant_b = await make_tenant(name="Access outsider")
    manager_a = await make_user(tenant_a, role="methodologist")
    manager_b = await make_user(tenant_b, role="methodologist")
    learner_a = await make_user(tenant_a, role="student")
    learner_b = await make_user(tenant_b, role="student")
    course_a = await make_course(tenant_a, manager_a, status="published")
    course_b = await make_course(tenant_b, manager_b, status="published")

    await set_current_tenant(tenant_a)
    enrollment_a = Enrollment(
        id=uuid4(),
        tenant_id=tenant_a.id,
        user_id=learner_a.id,
        course_id=course_a.id,
        status="enrolled",
        source="manual",
    )
    db_session.add(enrollment_a)
    await db_session.flush()

    await set_current_tenant(tenant_b)
    enrollment_b = Enrollment(
        id=uuid4(),
        tenant_id=tenant_b.id,
        user_id=learner_b.id,
        course_id=course_b.id,
        status="enrolled",
        source="manual",
    )
    db_session.add(enrollment_b)
    await db_session.flush()

    await set_current_tenant(tenant_a)
    await _expect_relationship_rejection(
        db_session,
        AssignmentAccessCredential(
            id=uuid4(),
            tenant_id=tenant_a.id,
            enrollment_id=enrollment_b.id,
            user_id=learner_a.id,
            token_hash=uuid4().hex,
            pin_hash="test-only-hash",
            expires_at=datetime.now(UTC) + timedelta(days=1),
        ),
    )


async def test_candidate_domain_accepts_active_methodologist_role_and_rejects_cross_tenant_links(
    db_session,
    make_tenant,
    make_user,
    make_course,
    set_current_tenant,
) -> None:
    tenant_a = await make_tenant(name="Candidate owner")
    tenant_b = await make_tenant(name="Candidate outsider")
    admin_a = await make_user(tenant_a, role="admin")
    manager_b = await make_user(tenant_b, role="methodologist")
    course_a = await make_course(tenant_a, admin_a, status="published")
    course_b = await make_course(tenant_b, manager_b, status="published")

    await set_current_tenant(tenant_a)
    db_session.add(UserRole(id=uuid4(), user_id=admin_a.id, tenant_id=tenant_a.id, role="methodologist"))
    release_a = ContentRelease(
        id=uuid4(),
        tenant_id=tenant_a.id,
        course_id=course_a.id,
        version=1,
        snapshot={"course": {"title": "A"}, "modules": []},
        snapshot_sha256="a" * 64,
        published_by=admin_a.id,
    )
    db_session.add(release_a)
    await db_session.flush()

    await set_current_tenant(tenant_b)
    release_b = ContentRelease(
        id=uuid4(),
        tenant_id=tenant_b.id,
        course_id=course_b.id,
        version=1,
        snapshot={"course": {"title": "B"}, "modules": []},
        snapshot_sha256="b" * 64,
        published_by=manager_b.id,
    )
    db_session.add(release_b)
    await db_session.flush()

    expires_at = datetime.now(UTC) + timedelta(days=7)
    await set_current_tenant(tenant_a)
    campaign_a = CandidateAssessmentCampaign(
        id=uuid4(),
        tenant_id=tenant_a.id,
        content_release_id=release_a.id,
        created_by=admin_a.id,
        title="Owner campaign",
        instructions="",
        status="active",
        expires_at=expires_at,
        attempt_limit=2,
        retention_days=180,
        assessment_snapshot={"quizzes": []},
        snapshot_sha256="c" * 64,
    )
    db_session.add(campaign_a)
    await db_session.flush()

    await _expect_relationship_rejection(
        db_session,
        CandidateAssessmentCampaign(
            id=uuid4(),
            tenant_id=tenant_a.id,
            content_release_id=release_b.id,
            created_by=admin_a.id,
            title="Cross-tenant release",
            instructions="",
            status="draft",
            expires_at=expires_at,
            attempt_limit=1,
            retention_days=180,
            assessment_snapshot={"quizzes": []},
            snapshot_sha256="d" * 64,
        ),
    )

    await set_current_tenant(tenant_b)
    campaign_b = CandidateAssessmentCampaign(
        id=uuid4(),
        tenant_id=tenant_b.id,
        content_release_id=release_b.id,
        created_by=manager_b.id,
        title="Outsider campaign",
        instructions="",
        status="active",
        expires_at=expires_at,
        attempt_limit=1,
        retention_days=180,
        assessment_snapshot={"quizzes": []},
        snapshot_sha256="e" * 64,
    )
    db_session.add(campaign_b)
    await db_session.flush()

    await set_current_tenant(tenant_a)
    candidate_a = AssessmentCandidate(
        id=uuid4(),
        tenant_id=tenant_a.id,
        campaign_id=campaign_a.id,
        first_name="Имя",
        last_name="Фамилия",
        status="active",
        retention_until=expires_at + timedelta(days=180),
    )
    db_session.add(candidate_a)
    await db_session.flush()

    for row in (
        AssessmentCandidate(
            id=uuid4(),
            tenant_id=tenant_a.id,
            campaign_id=campaign_b.id,
            first_name="Cross",
            last_name="Tenant",
            status="invited",
            retention_until=expires_at + timedelta(days=180),
        ),
        CandidateAccessCredential(
            id=uuid4(),
            tenant_id=tenant_a.id,
            campaign_id=campaign_b.id,
            candidate_id=candidate_a.id,
            token_hash=uuid4().hex,
            pin_hash="test-only-hash",
            expires_at=expires_at,
        ),
        CandidateAssessmentAttempt(
            id=uuid4(),
            tenant_id=tenant_a.id,
            campaign_id=campaign_b.id,
            candidate_id=candidate_a.id,
            attempt_number=1,
            status="started",
            assessment_snapshot={"quizzes": []},
            answers=[],
        ),
    ):
        await _expect_relationship_rejection(db_session, row)
