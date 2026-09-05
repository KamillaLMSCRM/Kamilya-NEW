from datetime import UTC, datetime, timedelta

import pytest

from app.modules.training_log.deadline_policy import classify_deadline


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
