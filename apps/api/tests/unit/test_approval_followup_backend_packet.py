import inspect
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest


def test_delivery_kind_is_constrained_and_invitation_default_is_preserved():
    from app.modules.course_approval.models import WorkflowDelivery

    assert WorkflowDelivery.message_kind.default.arg == "invitation"
    checks = {constraint.name: str(constraint.sqltext) for constraint in WorkflowDelivery.__table__.constraints if constraint.name and hasattr(constraint, "sqltext")}
    assert "course_review_reminder" in checks["ck_workflow_delivery_message_kind"]
    assert "course_review_overdue" in checks["ck_workflow_delivery_message_kind"]


def test_followup_email_signatures_cannot_accept_pin():
    from app.core.email import EmailService

    for name in ("send_course_review_reminder", "send_course_review_escalation"):
        assert "pin" not in inspect.signature(getattr(EmailService, name)).parameters


@pytest.mark.asyncio
async def test_email_service_captures_actual_pin_free_followup_arguments(monkeypatch):
    from app.core.email import EmailService

    calls = []

    async def capture(self, **kwargs):
        calls.append(kwargs)
        return "msg-followup"

    monkeypatch.setattr(EmailService, "_send", capture)
    due_at = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
    service = EmailService()
    assert await service.send_course_review_reminder(
        to_email="reviewer@example.test",
        reviewer_name="Reviewer",
        course_title="Safety",
        access_url="https://app.example.test/course-review-access/existing",
        due_at=due_at,
        idempotency_key="reminder/1",
    ) == "msg-followup"
    assert await service.send_course_review_escalation(
        to_email="requester@example.test",
        requester_name="Requester",
        course_title="Safety",
        action_url="/admin/course-approvals?courseId=00000000-0000-4000-8000-000000000001",
        due_at=due_at,
        idempotency_key="escalation/1",
    ) == "msg-followup"
    assert calls[0]["to_email"] == "reviewer@example.test"
    assert "PIN" not in calls[0]["text"]
    assert calls[1]["to_email"] == "requester@example.test"
    assert calls[1]["idempotency_key"] == "escalation/1"


def test_notification_inbox_contract_is_secret_free_and_has_no_reverse_approval_import():
    from app.modules.notifications.contracts import WorkflowNotificationIntentV1
    from app.modules.notifications.service import validate_action_path

    intent = WorkflowNotificationIntentV1(
        tenant_id=uuid4(), recipient_user_id=uuid4(), source_delivery_id=uuid4(),
        kind="course_review_assigned", course_title="Safety", due_at=None,
        action_path=f"/course-review-requests/{UUID('00000000-0000-4000-8000-000000000001')}",
    )
    assert intent.kind == "course_review_assigned"
    validate_action_path(intent.action_path)
    with pytest.raises(ValueError):
        validate_action_path("https://evil.example/course-review-requests/00000000-0000-4000-8000-000000000001")
    package_files = Path(__file__).parents[2] / "app" / "modules" / "notifications"
    assert not any("course_approval" in path.read_text(encoding="utf-8") for path in package_files.glob("*.py"))


def test_followup_materialization_preserves_delivery_transaction_and_tenant_integrity():
    service = Path(__file__).parents[2] / "app" / "modules" / "notifications" / "service.py"
    source = service.read_text(encoding="utf-8")
    assert "db.begin_nested()" in source
    assert "except IntegrityError" in source
    assert "await db.rollback()" not in source
    migration = Path(__file__).parents[2] / "alembic" / "versions" / "0150_approval_followup_notifications.py"
    migration_source = migration.read_text(encoding="utf-8")
    assert "enforce_notification_inbox_tenant_integrity" in migration_source
    assert "notification source delivery tenant mismatch" in migration_source
    assert "notification recipient tenant mismatch" in migration_source
    assert "notification source recipient mismatch" in migration_source


def test_request_followups_cover_both_cabinet_and_email_without_pin_payload_reuse():
    service = Path(__file__).parents[2] / "app" / "modules" / "course_approval" / "service.py"
    source = service.read_text(encoding="utf-8")
    assert "due_minus_24h/cabinet" in source
    assert "due_minus_24h/email" in source
    assert "due_overdue/cabinet" in source
    assert "due_overdue/email" in source
    assert 'followup_payload_encrypted = encrypt_config({"access_url": access_url})' in source
    worker = Path(__file__).parents[2] / "app" / "modules" / "course_approval" / "notification_tasks.py"
    worker_source = worker.read_text(encoding="utf-8")
    assert 'encrypt_config({"access_url": str(access_url)})' in worker_source
    assert "get_settings().PUBLIC_URL.rstrip('/')" in worker_source


def test_notification_http_routes_are_exact_and_neighbor_outbox_is_untouched():
    from app.modules.notifications.router import router

    routes = {(route.path, tuple(sorted(route.methods or set()))) for route in router.routes}
    assert ("/notifications", ("GET",)) in routes
    assert ("/notifications/{notification_id}/read", ("POST",)) in routes
    assert ("/notifications/read-all", ("POST",)) in routes
    enrollment_worker = Path(__file__).parents[2] / "app" / "modules" / "enrollments" / "notification_tasks.py"
    assert "course_review_reminder" not in enrollment_worker.read_text(encoding="utf-8")


def test_migration_is_additive_after_0149_with_force_rls_and_safe_downgrade():
    migration = Path(__file__).parents[2] / "alembic" / "versions" / "0150_approval_followup_notifications.py"
    source = migration.read_text(encoding="utf-8")
    assert 'revision = "0150"' in source
    assert 'down_revision = "0149"' in source
    assert "FORCE ROW LEVEL SECURITY" in source
    assert "Refusing destructive notification-inbox downgrade" in source


def test_root_registration_exposes_router_and_model():
    main = (Path(__file__).parents[2] / "app" / "main.py").read_text(encoding="utf-8")
    registry = (Path(__file__).parents[2] / "app" / "models" / "registry.py").read_text(encoding="utf-8")
    assert "from app.modules.notifications.router import router as notifications_router" in main
    assert 'app.include_router(notifications_router, prefix=f"{settings.API_PREFIX}")' in main
    assert '"app.modules.notifications.models"' in registry
