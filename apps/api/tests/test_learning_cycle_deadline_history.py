from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.modules.learning_cycles.schemas import DeadlineOverrideRequest

ROOT = Path(__file__).resolve().parents[3]


def test_deadline_override_requires_timezone_change_reason_and_meaningful_length():
    due = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
    body = DeadlineOverrideRequest(
        effective_due_at=due,
        reason="Сотрудник находится в подтвержденной командировке",
    )
    assert body.effective_due_at == due
    assert body.reason == "Сотрудник находится в подтвержденной командировке"

    with pytest.raises(ValidationError):
        DeadlineOverrideRequest(effective_due_at=due.replace(tzinfo=None), reason="Достаточно длинная причина переноса срока")
    with pytest.raises(ValidationError):
        DeadlineOverrideRequest(effective_due_at=due, reason="Слишком коротко")


def test_0167_is_additive_tenant_scoped_append_only_and_refuses_lossy_downgrade():
    migration = (
        ROOT / "apps/api/alembic/versions/0167_recurring_occurrence_deadline_history.py"
    ).read_text(encoding="utf-8")
    compact = migration.replace(" ", "")
    assert 'down_revision="0166"' in compact
    assert "sequence_no" in migration
    assert "content_release_id" in migration
    assert "effective_due_at" in migration
    assert "learning_cycle_participant_events" in migration
    assert "ENABLE ROW LEVEL SECURITY" in migration
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert "GRANT SELECT, INSERT" in migration
    assert "GRANT UPDATE" not in migration
    assert "REVOKE DELETE ON {course_occurrences} FROM lms_app" in migration
    assert "GRANT DELETE ON {schema}.recurring_learning_assignments TO lms_app" in migration
    assert "GRANT SELECT, INSERT ON {events} TO lms_app" in migration
    assert "freeze_recurring_occurrence_identity" in migration
    assert "freeze_learning_path_cycle_identity" in migration
    assert "reschedule_learning_reminder" in migration
    assert "status='queued' AND attempt_count=0 AND first_attempt_at IS NULL" in migration
    assert "OLD.enrollment_id IS NOT NULL AND NEW.enrollment_id IS DISTINCT FROM OLD.enrollment_id" in migration
    assert "0167 repair required: recurring occurrence lacks reciprocal enrollment release anchor" in migration
    assert "status IN ('sent','sending')" not in migration
    assert "0167 downgrade refused: deadline history exists" in migration


def test_training_log_and_reminders_use_effective_deadline_projection():
    training_log = (
        ROOT / "apps/api/app/modules/training_log/repository.py"
    ).read_text(encoding="utf-8")
    migration = (
        ROOT / "apps/api/alembic/versions/0167_recurring_occurrence_deadline_history.py"
    ).read_text(encoding="utf-8")
    assert "RecurringLearningAssignment.effective_due_at" in training_log
    assert "LearningPathCycleInstance.effective_due_at" in training_log
    assert "a.effective_due_at" in migration
    assert "i.effective_due_at" in migration


def test_original_and_effective_deadlines_remain_distinct_after_override():
    original = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
    effective = original + timedelta(days=5)
    assert original != effective
