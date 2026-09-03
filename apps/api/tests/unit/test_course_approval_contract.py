from uuid import uuid4
from pathlib import Path

import pytest
from fastapi import HTTPException


def test_permission_matrix_exposes_named_course_approval_permissions():
    from app.core.permissions import COURSE_APPROVAL_PERMISSIONS, role_has_permission

    assert role_has_permission("admin", COURSE_APPROVAL_PERMISSIONS.CONFIGURE)
    assert role_has_permission("methodologist", COURSE_APPROVAL_PERMISSIONS.CONFIGURE)
    assert role_has_permission("methodologist", COURSE_APPROVAL_PERMISSIONS.REQUEST)
    assert not role_has_permission("admin", COURSE_APPROVAL_PERMISSIONS.REQUEST)


@pytest.mark.asyncio
async def test_review_return_requires_reason_and_incomplete_approval_acknowledgement():
    from app.modules.course_approval.service import validate_decision

    with pytest.raises(HTTPException) as missing_reason:
        validate_decision("return", None, False, complete=True)
    assert missing_reason.value.status_code == 422

    with pytest.raises(HTTPException) as missing_ack:
        validate_decision("approve", None, False, complete=False)
    assert missing_ack.value.status_code == 409

    assert validate_decision("approve", None, True, complete=False)["warning_acknowledged"] is True


def test_course_approval_models_are_tenant_scoped_and_review_attempt_isolated():
    from app.modules.course_approval.models import CourseApprovalPolicy, CourseReviewAttempt, WorkflowAccessCredential

    tenant_id = uuid4()
    policy = CourseApprovalPolicy(tenant_id=tenant_id, course_id=uuid4())
    attempt = CourseReviewAttempt(tenant_id=tenant_id, revision_id=uuid4(), reviewer_user_id=uuid4())
    assert CourseApprovalPolicy.__table__.c.requires_approval.default.arg is False
    assert not hasattr(attempt, "enrollment_id")
    assert hasattr(WorkflowAccessCredential, "reviewer_user_id")


def test_course_approval_migration_keeps_rls_and_tenant_integrity_contract():
    migration = Path(__file__).parents[2] / "alembic" / "versions" / "0147_course_approval_workflow.py"
    source = migration.read_text(encoding="utf-8")
    assert "FORCE ROW LEVEL SECURITY" in source
    assert "enforce_course_approval_tenant_integrity" in source
    assert "reviewer_user_id" in source
    assert "lookup_course_review_tenant_by_token" in source
