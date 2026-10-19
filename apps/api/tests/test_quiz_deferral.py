"""Tests for quiz deferral logic."""
from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.quizzes import router
from app.modules.quizzes.models import Quiz
from app.modules.quizzes.service import _is_quiz_expired


class _FakeProgress:
    def __init__(self, completed_at):
        self.completed_at = completed_at


class _FakeQuiz:
    def __init__(self, lesson_id, deferral_days):
        self.lesson_id = lesson_id
        self.deferral_days = deferral_days


async def _mock_progress_lookup(db, user_id, lesson_id, tenant_id, completed_at):
    """Helper: mock db.execute to return a fake progress row."""
    mock = AsyncMock(spec=AsyncSession)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=_FakeProgress(completed_at))
    mock.execute = AsyncMock(return_value=mock_result)
    return mock


@pytest.mark.asyncio
async def test_deferral_not_expired_within_window():
    """Quiz is NOT expired if completed within deferral window."""
    now = datetime.now(timezone.utc)
    completed_at = now - timedelta(days=3)  # 3 days ago
    quiz = _FakeQuiz(lesson_id=uuid4(), deferral_days=7)
    user_id = uuid4()
    tenant_id = uuid4()

    db = await _mock_progress_lookup(db=None, user_id=user_id, lesson_id=quiz.lesson_id, tenant_id=tenant_id, completed_at=completed_at)
    assert await _is_quiz_expired(db, quiz, user_id, tenant_id) is False


@pytest.mark.asyncio
async def test_deferral_expired_outside_window():
    """Quiz IS expired if completed_at + deferral_days < now."""
    now = datetime.now(timezone.utc)
    completed_at = now - timedelta(days=10)  # 10 days ago
    quiz = _FakeQuiz(lesson_id=uuid4(), deferral_days=7)
    user_id = uuid4()
    tenant_id = uuid4()

    db = await _mock_progress_lookup(db=None, user_id=user_id, lesson_id=quiz.lesson_id, tenant_id=tenant_id, completed_at=completed_at)
    assert await _is_quiz_expired(db, quiz, user_id, tenant_id) is True


@pytest.mark.asyncio
async def test_deferral_no_progress_not_expired():
    """If user never completed the lesson, deferral hasn't started — quiz is NOT expired."""
    quiz = _FakeQuiz(lesson_id=uuid4(), deferral_days=7)
    user_id = uuid4()
    tenant_id = uuid4()

    mock = AsyncMock(spec=AsyncSession)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=None)
    mock.execute = AsyncMock(return_value=mock_result)

    assert await _is_quiz_expired(mock, quiz, user_id, tenant_id) is False


@pytest.mark.asyncio
async def test_deferral_zero_days_means_immediate_expiry():
    """deferral_days=0 means the deadline is completed_at itself (next second = expired)."""
    now = datetime.now(timezone.utc)
    completed_at = now - timedelta(seconds=5)
    quiz = _FakeQuiz(lesson_id=uuid4(), deferral_days=0)
    user_id = uuid4()
    tenant_id = uuid4()

    db = await _mock_progress_lookup(db=None, user_id=user_id, lesson_id=quiz.lesson_id, tenant_id=tenant_id, completed_at=completed_at)
    # 5 seconds > 0 seconds = expired
    assert await _is_quiz_expired(db, quiz, user_id, tenant_id) is True


def _result(*, rows=None, scalars=None, scalar=None):
    result = MagicMock()
    result.fetchall.return_value = rows or []
    result.scalars.return_value.all.return_value = scalars or []
    result.scalar_one_or_none.return_value = scalar
    return result


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("deferral_days", "completed_delta", "expected_expired"),
    [
        (0, timedelta(seconds=5), True),
        (7, timedelta(days=3), False),
        (7, timedelta(days=10), True),
    ],
)
async def test_enrolled_projection_matches_submission_deferral_semantics(
    monkeypatch,
    deferral_days,
    completed_delta,
    expected_expired,
):
    tenant_id, user_id, course_id, lesson_id, quiz_id, enrollment_id = [uuid4() for _ in range(6)]
    completed_at = datetime.now(UTC) - completed_delta
    user = SimpleNamespace(id=user_id, tenant_id=tenant_id)
    enrollment = SimpleNamespace(id=enrollment_id)
    quiz = SimpleNamespace(
        id=quiz_id,
        tenant_id=tenant_id,
        lesson_id=lesson_id,
        title="Deferral agreement",
        pass_score=80,
        attempt_limit=3,
        deferral_days=deferral_days,
    )
    db = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                _result(rows=[(course_id,)]),
                _result(rows=[(lesson_id, "Lesson", "Module", course_id)]),
                _result(scalars=[quiz]),
                _result(rows=[]),
                _result(scalar=completed_at),
            ]
        )
    )
    monkeypatch.setattr(router, "current_enrollment", AsyncMock(return_value=enrollment))

    projected = await router.list_enrolled_quizzes(db=db, user=user)
    submit_guard = await _is_quiz_expired(
        await _mock_progress_lookup(None, user_id, lesson_id, tenant_id, completed_at),
        quiz,
        user_id,
        tenant_id,
    )

    assert projected[0]["is_expired"] is expected_expired
    assert projected[0]["is_expired"] is submit_guard
