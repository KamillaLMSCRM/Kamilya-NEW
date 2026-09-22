"""Static public-contract checks for current versus historical learning reads."""

from types import SimpleNamespace
from uuid import uuid4

from app.modules.enrollments.context import scoped_enrollment_id
from app.modules.enrollments.occurrences import is_current_occurrence
from app.modules.training_log.schemas import TrainingLogFilter, TrainingLogSummary


def test_training_log_defaults_to_current_and_exposes_history_and_operational_metrics():
    assert TrainingLogFilter().history is False
    assert TrainingLogFilter(history=True).history is True
    summary = TrainingLogSummary(total=0, assigned=0, in_progress=0, completed=0)
    assert summary.failed_current == 0
    assert summary.exhausted_attempts == 0
    assert summary.reassigned == 0
    assert summary.cancelled_history == 0
    assert summary.superseded_history == 0


def test_current_occurrence_sql_excludes_a_predecessor_referenced_by_a_successor():
    sql = str(is_current_occurrence().compile(compile_kwargs={"literal_binds": True}))
    assert "NOT (EXISTS" in sql
    assert "previous_enrollment_id" in sql
    assert "tenant_id" in sql
    assert "user_id" in sql
    assert "course_id" in sql


def test_manual_repeat_gets_an_exact_state_scope_while_legacy_manual_keeps_null_scope():
    enrollment_id = uuid4()
    legacy = SimpleNamespace(id=enrollment_id, recurring_assignment_id=None, previous_enrollment_id=None)
    repeated = SimpleNamespace(id=enrollment_id, recurring_assignment_id=None, previous_enrollment_id=uuid4())
    assert scoped_enrollment_id(legacy) is None
    assert scoped_enrollment_id(repeated) == enrollment_id
