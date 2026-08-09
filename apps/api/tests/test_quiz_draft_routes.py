from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.quizzes import router
from app.modules.quizzes.schemas import QuizGenerateRequest


class _Db:
    def __init__(self, lesson):
        self.lesson = lesson

    async def get(self, _model, _identifier):
        return self.lesson


@pytest.mark.asyncio
async def test_generate_and_regenerate_draft_call_the_ai_builder(monkeypatch):
    tenant_id = uuid4()
    lesson_id = uuid4()
    quiz_id = uuid4()
    lesson = SimpleNamespace(id=lesson_id, tenant_id=tenant_id, title="Lesson", content="Source")
    db = _Db(lesson)
    user = SimpleNamespace(id=uuid4(), tenant_id=tenant_id, role="methodologist")
    request = QuizGenerateRequest(lesson_id=lesson_id, num_questions=3)
    builder = AsyncMock(
        return_value={
            "suggested_title": "Draft",
            "suggested_pass_score": 80,
            "questions": [{"text": "Question", "type": "MCQ", "points": 1, "choices": []}],
        }
    )
    monkeypatch.setattr(router, "build_quiz_draft", builder)

    generated = await router.generate_quiz(request, db, user)
    assert generated.suggested_title == "Draft"
    builder.assert_awaited_once_with(
        lesson_title="Lesson",
        lesson_content="Source",
        num_questions=3,
        difficulty="medium",
        language="ru",
        guidance=None,
    )

    builder.reset_mock()

    async def require_quiz(_db, requested_quiz_id, requested_tenant_id):
        assert requested_quiz_id == quiz_id
        assert requested_tenant_id == tenant_id
        return SimpleNamespace(id=quiz_id, lesson_id=lesson_id)

    monkeypatch.setattr(router, "_require_quiz_tenant", require_quiz)
    regenerated = await router.regenerate_quiz_draft(quiz_id, request, db, user)
    assert regenerated.suggested_title == "Draft"
    builder.assert_awaited_once_with(
        lesson_title="Lesson",
        lesson_content="Source",
        num_questions=3,
        difficulty="medium",
        language="ru",
        guidance=None,
    )
