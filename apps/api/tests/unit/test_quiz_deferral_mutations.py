"""Explicit quiz deferral values survive CRUD without weakening history guards."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.modules.quizzes import router
from app.modules.quizzes.schemas import QuizCreate, QuizUpdate


class QuizDb:
    def __init__(self, quiz=None, *, has_attempt=False):
        self.quiz = quiz
        self.has_attempt = has_attempt

    def add(self, quiz):
        self.quiz = quiz

    async def flush(self):
        if self.quiz.deferral_days is None:
            self.quiz.deferral_days = 7

    async def refresh(self, _quiz):
        pass

    async def get(self, _model, _id):
        return self.quiz

    async def execute(self, _query):
        return SimpleNamespace(scalar_one_or_none=lambda: uuid4() if self.has_attempt else None)


@pytest.mark.asyncio
@pytest.mark.parametrize("days", [0, 3, 7])
async def test_create_preserves_explicit_deferral(monkeypatch, days):
    user = SimpleNamespace(tenant_id=uuid4())
    db = QuizDb()
    monkeypatch.setattr(router, "get_quiz_with_questions", AsyncMock(return_value={}))
    await router.create_quiz(
        req=QuizCreate(lesson_id=uuid4(), title="Synthetic quiz", deferral_days=days), db=db, user=user
    )
    assert db.quiz.deferral_days == days


@pytest.mark.asyncio
@pytest.mark.parametrize("days", [0, 3, None])
async def test_update_preserves_zero_and_omitted_value(monkeypatch, days):
    user = SimpleNamespace(tenant_id=uuid4())
    quiz = SimpleNamespace(id=uuid4(), tenant_id=user.tenant_id, deferral_days=7)
    db = QuizDb(quiz)
    monkeypatch.setattr(router, "get_quiz_with_questions", AsyncMock(return_value={}))
    await router.update_quiz(quiz_id=quiz.id, req=QuizUpdate(deferral_days=days), db=db, user=user)
    assert quiz.deferral_days == (7 if days is None else days)


@pytest.mark.asyncio
@pytest.mark.parametrize("foreign,has_attempt,expected", [(True, False, 404), (False, True, 409)])
async def test_deferral_update_preserves_tenant_and_attempt_guards(foreign, has_attempt, expected):
    user = SimpleNamespace(tenant_id=uuid4())
    quiz = SimpleNamespace(id=uuid4(), tenant_id=uuid4() if foreign else user.tenant_id, deferral_days=7)
    db = QuizDb(quiz, has_attempt=has_attempt)
    with pytest.raises(HTTPException) as exc:
        await router.update_quiz(quiz_id=quiz.id, req=QuizUpdate(deferral_days=0), db=db, user=user)
    assert exc.value.status_code == expected
    assert quiz.deferral_days == 7


@pytest.mark.parametrize("days", [-1, 3651])
def test_deferral_rejects_negative_or_unbounded_days(days):
    with pytest.raises(ValidationError):
        QuizCreate(lesson_id=uuid4(), title="QA", deferral_days=days)
    with pytest.raises(ValidationError):
        QuizUpdate(deferral_days=days)
