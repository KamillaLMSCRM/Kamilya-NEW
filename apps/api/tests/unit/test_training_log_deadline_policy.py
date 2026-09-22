from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.models.enrollment import Enrollment
from app.models.users import User
from app.modules.training_log.deadline_policy import (
    CERTIFICATE_EXPIRING_SOON,
    classify_certificate_status,
    classify_deadline,
    classify_operational_deadline,
)
from app.modules.training_log.repository import _join_cycle_read_model


def test_deadline_policy_covers_legacy_open_overdue_and_completion_states():
    now = datetime(2026, 9, 5, 9, 0, tzinfo=UTC)

    assert classify_deadline(due_at=None, completed_at=None, now=now) == "not_applicable"
    assert classify_deadline(due_at=now, completed_at=None, now=now) == "active"
    assert classify_deadline(due_at=now - timedelta(seconds=1), completed_at=None, now=now) == "overdue"
    assert classify_deadline(due_at=now, completed_at=now, now=now) == "completed_on_time"
    assert (
        classify_deadline(
            due_at=now,
            completed_at=now + timedelta(seconds=1),
            now=now,
        )
        == "completed_late"
    )


@pytest.mark.parametrize("eligible", [False, True])
def test_completed_without_timestamp_never_claims_punctuality(eligible):
    now = datetime(2026, 9, 5, 9, 0, tzinfo=UTC)
    assert (
        classify_deadline(
            due_at=now - timedelta(days=1),
            completed_at=None,
            now=now,
            enrollment_status="completed",
            eligible=eligible,
        )
        == "not_applicable"
    )


@pytest.mark.parametrize("completed", [False, True])
def test_cancelled_or_skipped_cycle_is_not_an_attention_item(completed):
    now = datetime(2026, 9, 5, 9, 0, tzinfo=UTC)
    assert (
        classify_deadline(
            due_at=now - timedelta(days=1),
            completed_at=now if completed else None,
            now=now,
            eligible=False,
        )
        == "not_applicable"
    )


def test_operational_deadline_states_keep_legacy_rows_without_deadlines_as_none():
    now = datetime(2026, 9, 5, 9, 0, tzinfo=UTC)

    assert classify_operational_deadline(due_at=None, completed_at=None, now=now) == "none"
    assert (
        classify_operational_deadline(due_at=now, completed_at=None, now=now)
        == "upcoming"
    )
    assert (
        classify_operational_deadline(due_at=now - timedelta(seconds=1), completed_at=None, now=now)
        == "overdue"
    )
    assert (
        classify_operational_deadline(due_at=now, completed_at=now, now=now)
        == "completed_on_time"
    )
    assert (
        classify_operational_deadline(
            due_at=now,
            completed_at=now + timedelta(microseconds=1),
            now=now,
        )
        == "completed_late"
    )
    assert (
        classify_operational_deadline(
            due_at=now - timedelta(days=1),
            completed_at=None,
            now=now,
            enrollment_status="completed",
        )
        == "none"
    )


@pytest.mark.parametrize(
    ("expires_delta", "revoked", "exists", "expected"),
    [
        (None, False, False, "none"),
        (None, False, True, "active"),
        (timedelta(days=31), False, True, "active"),
        (CERTIFICATE_EXPIRING_SOON, False, True, "expiring"),
        (timedelta(seconds=1), False, True, "expiring"),
        (timedelta(0), False, True, "expired"),
        (timedelta(days=-1), False, True, "expired"),
        (timedelta(days=-1), True, True, "revoked"),
    ],
)
def test_certificate_status_uses_explicit_30_day_window(expires_delta, revoked, exists, expected):
    now = datetime(2026, 9, 5, 9, 0, tzinfo=UTC)
    assert classify_certificate_status(
        expires_at=now + expires_delta if expires_delta is not None else None,
        revoked_at=now if revoked else None,
        certificate_exists=exists,
        now=now,
    ) == expected


def test_access_policy_deadline_join_is_bound_to_tenant_and_exact_enrollment():
    tenant_id = uuid4()
    statement = select(User).join(Enrollment, Enrollment.user_id == User.id)
    statement, columns = _join_cycle_read_model(statement, tenant_id)
    compiled = statement.compile(dialect=postgresql.dialect())

    assert "enrollment_access_policies.enrollment_id = enrollments.id" in str(compiled)
    assert "enrollment_access_policies.user_id = enrollments.user_id" in str(compiled)
    assert "enrollment_access_policies.tenant_id =" in str(compiled)
    assert "recurring_learning_assignments.enrollment_id = enrollments.id" in str(compiled)
    assert "recurring_learning_assignments.tenant_id =" in str(compiled)
    assert tenant_id in compiled.params.values()
    assert columns.assignment_due_at is not None
