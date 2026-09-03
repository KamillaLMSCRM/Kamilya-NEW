from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException


def test_permission_matrix_exposes_named_course_approval_permissions():
    from app.core.permissions import COURSE_APPROVAL_PERMISSIONS, role_has_permission

    assert role_has_permission("admin", COURSE_APPROVAL_PERMISSIONS.CONFIGURE)
    assert role_has_permission("methodologist", COURSE_APPROVAL_PERMISSIONS.CONFIGURE)
    assert role_has_permission("methodologist", COURSE_APPROVAL_PERMISSIONS.REVIEW)
    assert role_has_permission("methodologist", COURSE_APPROVAL_PERMISSIONS.REQUEST)
    assert not role_has_permission("admin", COURSE_APPROVAL_PERMISSIONS.REQUEST)
    assert not role_has_permission("admin", COURSE_APPROVAL_PERMISSIONS.REVIEW)


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


@pytest.mark.asyncio
async def test_tenant_context_failure_is_fail_closed_before_orm_access():
    from app.core.auth import _set_tenant_security_context

    class BrokenSession:
        def __init__(self):
            self.rolled_back = False

        async def execute(self, statement, params):
            raise RuntimeError("set_current_tenant unavailable")

        async def rollback(self):
            self.rolled_back = True

    db = BrokenSession()
    with pytest.raises(HTTPException) as failure:
        await _set_tenant_security_context(db, str(uuid4()))
    assert failure.value.status_code == 503
    assert db.rolled_back is True


def test_course_approval_models_are_tenant_scoped_and_review_attempt_isolated():
    from app.modules.course_approval.models import (
        CourseApprovalPolicy,
        CourseReviewAttempt,
        WorkflowAccessCredential,
        WorkflowDelivery,
    )

    tenant_id = uuid4()
    CourseApprovalPolicy(tenant_id=tenant_id, course_id=uuid4())
    attempt = CourseReviewAttempt(tenant_id=tenant_id, revision_id=uuid4(), reviewer_user_id=uuid4())
    assert CourseApprovalPolicy.__table__.c.requires_approval.default.arg is False
    assert not hasattr(attempt, "enrollment_id")
    assert hasattr(WorkflowAccessCredential, "reviewer_user_id")
    assert hasattr(WorkflowDelivery, "recipient_email")
    assert hasattr(WorkflowDelivery, "payload_encrypted")


def test_course_approval_migration_keeps_rls_and_tenant_integrity_contract():
    migration = Path(__file__).parents[2] / "alembic" / "versions" / "0147_course_approval_workflow.py"
    source = migration.read_text(encoding="utf-8")
    assert "FORCE ROW LEVEL SECURITY" in source
    assert "enforce_course_approval_tenant_integrity" in source
    assert "reviewer_user_id" in source
    assert "lookup_course_review_tenant_by_token" in source
    assert "due_course_approval_deliveries" in source
    assert "due_course_approval_deadlines" in source
    assert "lms_recovery" in source
    assert source.count("SECURITY DEFINER") >= 3


def test_reviewer_snapshot_redacts_answer_keys_without_mutating_release_snapshot():
    from app.modules.course_approval.service import learner_safe_review_snapshot

    source = {
        "schema_version": 1,
        "course": {"tenant_id": "tenant-secret", "title": "Course"},
        "modules": [{"lessons": [{"quizzes": [{"questions": [{"choices": [{"id": "a", "is_correct": True}]}]}]}]}],
    }
    safe = learner_safe_review_snapshot(source)
    assert "tenant_id" not in safe["course"]
    assert "is_correct" not in safe["modules"][0]["lessons"][0]["quizzes"][0]["questions"][0]["choices"][0]
    assert source["modules"][0]["lessons"][0]["quizzes"][0]["questions"][0]["choices"][0]["is_correct"] is True


def test_review_scoring_is_server_derived_and_requires_all_questions_for_completion():
    from app.modules.course_approval.service import score_review_submission

    snapshot = {"modules": [{"lessons": [{"quizzes": [{"questions": [{"id": "q1", "choices": [{"id": "a", "is_correct": True}, {"id": "b", "is_correct": False}]}, {"id": "q2", "choices": [{"id": "c", "is_correct": True}]}]}]}]}]}
    result = score_review_submission(snapshot, [{"question_id": "q1", "selected_choice_ids": ["a"]}])
    assert result == {"answered": 1, "total": 2, "correct": 1, "score_percent": 50.0, "complete": False}


def test_guest_review_contract_is_scoped_and_migration_handles_guest_identity():
    from app.modules.course_approval.models import CourseApprovalReviewer

    assert CourseApprovalReviewer.__table__.c.reviewer_user_id.nullable is True
    assert CourseApprovalReviewer.__table__.c.reviewer_email.nullable is True
    migration = Path(__file__).parents[2] / "alembic" / "versions" / "0147_course_approval_workflow.py"
    source = migration.read_text(encoding="utf-8")
    assert "NEW.reviewer_user_id IS NOT NULL AND NEW.reviewer_email IS NULL" in source


def test_review_pin_path_uses_fail_closed_tenant_context_helper():
    service = Path(__file__).parents[2] / "app" / "modules" / "course_approval" / "service.py"
    source = service.read_text(encoding="utf-8")
    assert "await _set_tenant_security_context(db, str(tenant_id))" in source
    assert "SELECT set_current_tenant(:tid)" not in source


def test_course_approval_workflow_has_runtime_kill_switch():
    config = Path(__file__).parents[2] / "app" / "core" / "config.py"
    router = Path(__file__).parents[2] / "app" / "modules" / "course_approval" / "router.py"
    assert "COURSE_APPROVAL_WORKFLOW_ENABLED: bool = True" in config.read_text(encoding="utf-8")
    assert "require_course_approval_enabled" in router.read_text(encoding="utf-8")
    router_source = router.read_text(encoding="utf-8")
    assert "workflow_write = tenant" in router_source
    assert 'router = APIRouter(tags=["course-approval"])' in router_source
    courses_source = (Path(__file__).parents[2] / "app" / "modules" / "courses" / "router.py").read_text(encoding="utf-8")
    assert "approval_pending" in courses_source
    assert "COURSE_APPROVAL_WORKFLOW_ENABLED" not in courses_source


def test_scoped_projection_and_decision_pending_are_explicit_contracts():
    router = Path(__file__).parents[2] / "app" / "modules" / "course_approval" / "router.py"
    schemas = Path(__file__).parents[2] / "app" / "modules" / "course_approval" / "schemas.py"
    service = Path(__file__).parents[2] / "app" / "modules" / "course_approval" / "service.py"
    router_source = router.read_text(encoding="utf-8")
    schemas_source = schemas.read_text(encoding="utf-8")
    service_source = service.read_text(encoding="utf-8")
    assert '"/course-review-requests"' in router_source
    assert '"/course-review-requests/{request_id}"' in router_source
    assert "ScopedReviewRequestResponse" in schemas_source
    assert '"decision_pending"' in router_source
    assert 'effective_state = "decision_pending"' in service_source


def test_review_credentials_are_reusable_and_resend_rotation_is_explicit():
    service = Path(__file__).parents[2] / "app" / "modules" / "course_approval" / "service.py"
    source = service.read_text(encoding="utf-8")
    assert "rotate_credentials" in source
    assert "Only retryable failed deliveries" in source
    assert "PIN verification is not single-use" in source
    router = Path(__file__).parents[2] / "app" / "modules" / "course_approval" / "router.py"
    router_source = router.read_text(encoding="utf-8")
    assert "credentials_already_issued" in router_source
    assert '"access_credentials": []' in router_source


def test_mixed_guest_and_internal_reviewer_contract_keeps_per_reviewer_identity():
    from app.modules.course_approval.models import CourseApprovalReviewer, WorkflowAccessCredential

    tenant_id = uuid4()
    revision_id = uuid4()
    internal_id = uuid4()
    guest = CourseApprovalReviewer(tenant_id=tenant_id, revision_id=revision_id, reviewer_email="guest@example.test", reviewer_name="Guest")
    internal = CourseApprovalReviewer(tenant_id=tenant_id, revision_id=revision_id, reviewer_user_id=internal_id)
    assert guest.reviewer_user_id is None and guest.reviewer_email == "guest@example.test"
    assert internal.reviewer_user_id == internal_id and internal.reviewer_email is None
    assert WorkflowAccessCredential.__table__.c.work_item_id.nullable is False


def test_append_only_and_terminal_delivery_controls_are_migration_contracts():
    migration = Path(__file__).parents[2] / "alembic" / "versions" / "0147_course_approval_workflow.py"
    source = migration.read_text(encoding="utf-8")
    assert "REVOKE DELETE" in source
    assert "Refusing destructive course-approval downgrade" in source
    assert "'terminal'" in source
    worker = Path(__file__).parents[2] / "app" / "modules" / "course_approval" / "notification_tasks.py"
    worker_source = worker.read_text(encoding="utf-8")
    assert 'status.in_(("queued", "failed"))' in worker_source
    assert 'status = "terminal"' in worker_source


def test_migration_checks_internal_actor_and_recipient_tenant_ownership():
    migration = Path(__file__).parents[2] / "alembic" / "versions" / "0147_course_approval_workflow.py"
    source = migration.read_text(encoding="utf-8")
    assert "policy actor tenant mismatch" in source
    assert "revision actor tenant mismatch" in source
    assert "requester tenant mismatch" in source
    assert "recipient tenant mismatch" in source


def test_personal_link_reminders_never_depend_on_plaintext_secret_payloads():
    service = Path(__file__).parents[2] / "app" / "modules" / "course_approval" / "service.py"
    worker = Path(__file__).parents[2] / "app" / "modules" / "course_approval" / "notification_tasks.py"
    service_source = service.read_text(encoding="utf-8")
    worker_source = worker.read_text(encoding="utf-8")
    assert 'reminder_channel = "email" if delivery_mode == "email" else "cabinet"' in service_source
    assert 'payload_encrypted=original.payload_encrypted' in worker_source
    assert 'item.deadline_state = "overdue"' in worker_source
    assert "PIN" not in worker_source


def test_course_approval_delivery_worker_is_retryable_and_deadline_aware():
    worker = Path(__file__).parents[2] / "app" / "modules" / "course_approval" / "notification_tasks.py"
    source = worker.read_text(encoding="utf-8")
    assert "with_for_update(skip_locked=True)" in source
    assert "attempt_count < 8" in source
    assert "recover_workflow_deliveries" in source
    assert "recover_workflow_deadlines" in source
    assert 'item.deadline_state = "overdue"' in source


def test_course_approval_mutations_have_persisted_idempotency_boundaries():
    router = Path(__file__).parents[2] / "app" / "modules" / "course_approval" / "router.py"
    courses = Path(__file__).parents[2] / "app" / "modules" / "courses" / "router.py"
    approval_source = router.read_text(encoding="utf-8")
    assert approval_source.count('alias="Idempotency-Key"') >= 7
    assert 'operation="course_review.progress"' in approval_source
    assert 'operation="course_review.test"' in approval_source
    assert 'operation="course_review.decision"' in approval_source
    assert 'operation="course_approval.resend"' in approval_source
    assert 'operation="course.publish"' in courses.read_text(encoding="utf-8")
    assert 'operation="course.unpublish"' in courses.read_text(encoding="utf-8")
