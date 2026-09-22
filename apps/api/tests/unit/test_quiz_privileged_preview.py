from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from app.modules.quizzes import router, service
from app.modules.quizzes.schemas import QuizSubmission
from app.modules.quizzes.service import QuizScoringResult


class NoPersistenceDb:
    """Fails the test if the preview route tries to create learner state."""

    def add(self, *_args, **_kwargs):
        raise AssertionError("preview submission must not add persistent state")

    async def flush(self):
        raise AssertionError("preview submission must not flush persistent state")

    async def refresh(self, *_args, **_kwargs):
        raise AssertionError("preview submission must not refresh persistent state")


@pytest.mark.asyncio
async def test_privileged_preview_uses_shared_scoring_without_learner_persistence(monkeypatch):
    tenant_id, user_id, quiz_id, question_id, correct_choice_id = (uuid4() for _ in range(5))
    user = SimpleNamespace(id=user_id, tenant_id=tenant_id, role="methodologist")
    quiz = SimpleNamespace(id=quiz_id, lesson_id=uuid4())
    scoring = QuizScoringResult(
        score_percent=100,
        total_points=2,
        earned_points=2,
        passed=True,
        graded_answers=[
            {
                "question_id": str(question_id),
                "selected_choice_ids": [str(correct_choice_id)],
                "correct_choice_ids": [str(correct_choice_id)],
                "is_correct": True,
                "points_earned": 2,
                "points_possible": 2,
            }
        ],
    )
    require_preview_access = AsyncMock(return_value=quiz)
    evaluate = AsyncMock(return_value=scoring)
    learner_grade = AsyncMock(side_effect=AssertionError("preview must not use learner persistence"))

    monkeypatch.setattr(router, "_require_quiz_preview_access", require_preview_access)
    monkeypatch.setattr(router, "evaluate_quiz_submission", evaluate)
    monkeypatch.setattr(router, "grade_quiz", learner_grade)

    db = NoPersistenceDb()
    response = await router.preview_submit_quiz(
        quiz_id=quiz_id,
        req=QuizSubmission(
            answers=[{"question_id": question_id, "selected_choice_ids": [correct_choice_id]}],
            time_spent_seconds=15,
        ),
        db=db,  # type: ignore[arg-type]
        user=user,
    )

    assert response.quiz_id == quiz_id
    assert response.score_percent == 100
    assert response.total_points == 2
    assert response.earned_points == 2
    assert response.passed is True
    assert response.graded_answers[0].question_id == question_id
    assert response.graded_answers[0].selected_choice_ids == [correct_choice_id]
    assert response.graded_answers[0].correct_choice_ids == [correct_choice_id]
    assert "attempt" not in response.model_dump()
    require_preview_access.assert_awaited_once_with(db, quiz_id, user)
    evaluate.assert_awaited_once_with(
        db=db,
        quiz_id=quiz_id,
        tenant_id=tenant_id,
        answers=[{"question_id": question_id, "selected_choice_ids": [correct_choice_id]}],
    )
    learner_grade.assert_not_awaited()


@pytest.mark.asyncio
async def test_privileged_preview_allows_tenant_owned_quiz_without_lesson(monkeypatch):
    tenant_id, user_id, quiz_id = (uuid4() for _ in range(3))
    user = SimpleNamespace(id=user_id, tenant_id=tenant_id, role="methodologist")
    quiz = SimpleNamespace(id=quiz_id, lesson_id=None)
    require_tenant = AsyncMock(return_value=quiz)
    require_lesson = AsyncMock()
    monkeypatch.setattr(router, "_require_quiz_tenant", require_tenant)
    monkeypatch.setattr(router, "require_lesson_access", require_lesson)
    db = SimpleNamespace()

    result = await router._require_quiz_preview_access(db, quiz_id, user)

    assert result is quiz
    require_tenant.assert_awaited_once_with(db, quiz_id, tenant_id)
    require_lesson.assert_not_awaited()


@pytest.mark.asyncio
async def test_preview_scoring_rejects_question_without_valid_answer_key():
    tenant_id, quiz_id, question_id, choice_id = (uuid4() for _ in range(4))
    quiz = SimpleNamespace(id=quiz_id, pass_score=80)
    question = SimpleNamespace(id=question_id, points=1)
    invalid_choice = SimpleNamespace(
        id=choice_id,
        question_id=question_id,
        is_correct=False,
        order_index=0,
    )

    def rows(items):
        result = Mock()
        result.scalars.return_value.all.return_value = items
        return result

    db = SimpleNamespace(
        scalar=AsyncMock(return_value=quiz),
        execute=AsyncMock(side_effect=[rows([question]), rows([invalid_choice])]),
    )

    with pytest.raises(ValueError, match="without a valid answer key"):
        await service.evaluate_quiz_submission(
            db=db,  # type: ignore[arg-type]
            quiz_id=quiz_id,
            tenant_id=tenant_id,
            answers=[{"question_id": question_id, "selected_choice_ids": []}],
        )


@pytest.mark.asyncio
async def test_learner_submission_delegates_to_the_preview_scoring_evaluator(monkeypatch):
    tenant_id, user_id, quiz_id, lesson_id = (uuid4() for _ in range(4))
    quiz = SimpleNamespace(
        id=quiz_id,
        lesson_id=lesson_id,
        title="Safety check",
        pass_score=80,
        time_limit=None,
        attempt_limit=3,
        deferral_days=7,
    )
    scoring = QuizScoringResult(
        score_percent=100,
        total_points=1,
        earned_points=1,
        passed=True,
        graded_answers=[],
        quiz=quiz,
        questions=[],
        choices_by_question={},
    )
    enrollment = SimpleNamespace(id=uuid4(), content_release_id=uuid4())
    course = SimpleNamespace(id=uuid4())
    db = SimpleNamespace(
        scalar=AsyncMock(side_effect=[quiz, course, 0, "a" * 64]),
        add=Mock(),
        flush=AsyncMock(),
        refresh=AsyncMock(),
    )
    evaluator = AsyncMock(return_value=scoring)
    monkeypatch.setattr(service, "evaluate_quiz_submission", evaluator)
    monkeypatch.setattr(service, "_is_quiz_expired", AsyncMock(return_value=False))

    from app.modules.enrollments import context as enrollment_context

    monkeypatch.setattr(enrollment_context, "current_enrollment", AsyncMock(return_value=enrollment))

    result = await service.grade_quiz(
        db=db,  # type: ignore[arg-type]
        quiz_id=quiz_id,
        user_id=user_id,
        tenant_id=tenant_id,
        answers=[],
    )

    evaluator.assert_awaited_once_with(db, quiz_id, tenant_id, [])
    assert result["attempt"].score_percent == scoring.score_percent
    assert result["attempt"].earned_points == scoring.earned_points
    assert result["attempt"].passed is scoring.passed
