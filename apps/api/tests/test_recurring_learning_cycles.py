from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.modules.learning_cycles import service as cycle_service
from app.modules.learning_cycles.router import activate, occurrence_reporting_status

ROOT = Path(__file__).resolve().parents[3]


class ScalarDb:
    def __init__(self, values):
        self.values = iter(values)

    async def scalar(self, _statement):
        return next(self.values)


@pytest.mark.asyncio
async def test_native_rule_activation_schedules_first_occurrence():
    tenant_id = uuid4()
    rule = SimpleNamespace(course_id=uuid4(), status="draft", next_run_at=None)
    course = SimpleNamespace(status="published", delivery_type="native")
    result = await activate(uuid4(), db=ScalarDb([rule, course]), user=SimpleNamespace(tenant_id=tenant_id))
    assert result.status == "active"
    assert result.next_run_at is not None


@pytest.mark.asyncio
async def test_global_recovery_fails_closed_without_dedicated_url(monkeypatch):
    monkeypatch.setattr(
        cycle_service,
        "get_settings",
        lambda: SimpleNamespace(ASSIGNMENT_RECOVERY_DATABASE_URL=""),
    )
    with pytest.raises(RuntimeError, match="ASSIGNMENT_RECOVERY_DATABASE_URL"):
        await cycle_service.recover_due()


def test_occurrence_reporting_status_before_due_overdue_and_completed_late():
    now = datetime.now(UTC)
    assert (
        occurrence_reporting_status(
            stored_status="assigned", due_at=now + timedelta(days=1), completed_at=None, now=now
        )
        == "assigned"
    )
    assert (
        occurrence_reporting_status(
            stored_status="assigned", due_at=now - timedelta(seconds=1), completed_at=None, now=now
        )
        == "overdue"
    )
    assert (
        occurrence_reporting_status(
            stored_status="completed", due_at=now - timedelta(days=1), completed_at=now, now=now
        )
        == "completed_late"
    )


def test_0103_adds_independent_occurrence_identity_and_safe_downgrade():
    migration = (ROOT / "apps/api/alembic/versions/0103_recurring_enrollment_instances.py").read_text(encoding="utf-8")
    compact = migration.replace(" ", "")
    assert 'down_revision="0102"' in compact
    assert "recurring_assignment_id" in migration
    assert "uq_progress_enrollment_lesson" in migration
    assert "uq_certificates_enrollment" in migration
    assert "validate_recurring_enrollment_identity" in migration
    assert "validate_progress_enrollment_identity" in migration
    assert "validate_certificate_enrollment_identity" in migration
    assert "SECURITY DEFINER" in migration
    assert "least(p_limit,100)" in migration
    assert "FROM PUBLIC, lms_app" in migration
    assert "TO lms_recovery" in migration
    assert "uq_certificates_legacy_user_course" in migration
    assert "ix_certificates_user_course" in migration
    assert "0103 downgrade refused: recurring enrollments exist" in migration
    assert "enrollments NO FORCE ROW LEVEL SECURITY" in migration
    assert "enrollments FORCE ROW LEVEL SECURITY" in migration


def test_materializer_creates_distinct_enrollment_and_uses_durable_outbox():
    service = (ROOT / "apps/api/app/modules/learning_cycles/service.py").read_text(encoding="utf-8")
    assert "recurring_assignment_id=occurrence.id" in service
    assert "queue_manual_enrollment_notification" in service
    assert "await db.commit()" in service
    assert service.index("await db.commit()") < service.index("apply_async")


def test_progress_attempt_certificate_and_log_are_enrollment_scoped():
    progress = (ROOT / "apps/api/app/modules/progress/service.py").read_text(encoding="utf-8")
    quizzes = (ROOT / "apps/api/app/modules/quizzes/service.py").read_text(encoding="utf-8")
    certificates = (ROOT / "apps/api/app/modules/certificates/service.py").read_text(encoding="utf-8")
    training_log = (ROOT / "apps/api/app/modules/training_log/repository.py").read_text(encoding="utf-8")
    assert "Progress.enrollment_id" in progress
    assert "QuizAttempt.enrollment_id == enrollment.id" in quizzes
    assert "certificate_enrollment_id" in certificates
    assert "native_activity.c.enrollment_id == Enrollment.id" in training_log
    assert 'r["enrollment_id"]' in training_log


def test_scheduler_and_broker_independent_recovery_are_registered():
    celery = (ROOT / "apps/api/app/core/celery_app.py").read_text(encoding="utf-8")
    operations = (ROOT / "apps/api/app/modules/admin/superadmin/operations.py").read_text(encoding="utf-8")
    timer = (ROOT / "infra/systemd/kamilya-learning-cycle-recovery.timer").read_text(encoding="utf-8")
    for task in ("learning_cycles.materialize", "learning_cycles.recover_due"):
        assert task in celery
        assert task in operations
    assert "OnUnitActiveSec=1min" in timer
    service = (ROOT / "apps/api/app/modules/learning_cycles/service.py").read_text(encoding="utf-8")
    assert "ASSIGNMENT_RECOVERY_DATABASE_URL" in service
    assert "create_async_engine" in service
