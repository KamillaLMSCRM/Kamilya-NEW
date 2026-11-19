"""The two languages must share identities and one native grading contract."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.modules.ai.schemas import AIGenerateRequest
from app.modules.courses.localization_router import course_languages
from app.modules.courses.localizations import (
    POLICY_KEY,
    ensure_requested_languages,
    source_fields,
    validate_edition,
)


def _snapshot():
    return {
        "release_version": 1,
        "course": {"id": "c", "title": "Обучение"},
        "modules": [{"id": "m", "title": "Подготовка", "lessons": [{
            "id": "l", "title": "Инструкция", "content_type": "text",
            "content": "[Видео](https://www.youtube.com/watch?v=dQw4w9WgXcQ&start=42&end=63)\nПроверьте 2 позиции.",
            "content_blocks": [], "quizzes": [{"id": "z", "title": "Проверка", "pass_score": 80,
                                               "attempt_limit": 3, "review_status": "pending",
                                               "questions": [{"id": "q", "text": "Сколько позиций?", "type": "single_choice",
                                                              "points": 1, "explanation": "Нужны 2 позиции.",
                                                              "choices": [{"id": "x", "text": "2", "is_correct": True},
                                                                          {"id": "y", "text": "3", "is_correct": False}]}]}],
        }]}],
    }


def test_release_metadata_keeps_translation_but_grading_changes_invalidate_it():
    approved = _snapshot()
    edited = deepcopy(approved)
    edited["release_version"] = 2
    quiz = edited["modules"][0]["lessons"][0]["quizzes"][0]
    quiz["review_status"] = "approved"
    assert source_fields(edited) == source_fields(approved)

    quiz["questions"][0]["choices"][0]["is_correct"] = False
    quiz["questions"][0]["choices"][1]["is_correct"] = True
    actual, translated_fields = source_fields(edited)
    expected, original_fields = source_fields(approved)
    assert original_fields == translated_fields
    assert actual != expected


def test_translation_preserves_media_numbers_and_exact_field_set():
    _, source = source_fields(_snapshot())
    candidate = {**source, "question.q.text": "Неше позиция бар?"}
    validate_edition(source, candidate)

    for replacement in ({"lesson.l.content": source["lesson.l.content"].replace("42", "41")},
                        {"choice.x.text": "4"}, {"course.unrelated.title": "Жалған"}):
        with pytest.raises(HTTPException) as caught:
            validate_edition(source, {**candidate, **replacement})
        assert caught.value.status_code == 422


@pytest.mark.asyncio
async def test_learner_locale_projection_uses_assignment_release_without_assessment_payload():
    course = SimpleNamespace(id=uuid4(), delivery_type="native", source_analysis={
        POLICY_KEY: {"primary": "ru", "requested": ["ru", "kk"]},
    })
    user = SimpleNamespace(id=uuid4(), role="student")
    db = AsyncMock()
    candidate = {"lesson.l.title": "Нұсқаулық", "question.q.explanation": "Жауап"}
    with patch("app.modules.courses.localization_router.require_course_access", return_value=course), \
         patch("app.modules.courses.localization_router.learner_snapshot", return_value=_snapshot()) as bound, \
         patch("app.modules.courses.localization_router.editions", return_value=[{"language": "kk", "content": candidate}]) as editions:
        result = await course_languages(course.id, db, user, language="kk")
    bound.assert_awaited_once_with(db, course, user)
    assert editions.await_args.kwargs == {"published": True}
    assert result == {"primary": "ru", "available": ["ru", "kk"], "content": {"lesson.l.title": "Нұсқаулық"}}


@pytest.mark.asyncio
async def test_requested_translation_must_be_approved_before_publication():
    course = SimpleNamespace(source_analysis={POLICY_KEY: {"primary": "ru", "requested": ["ru", "kk"]}})
    db = AsyncMock()
    with patch("app.modules.courses.localizations.editions", return_value=[]):
        with pytest.raises(HTTPException) as caught:
            await ensure_requested_languages(db, course, _snapshot())
    assert caught.value.status_code == 409
    with patch("app.modules.courses.localizations.editions", return_value=[{"language": "kk"}]):
        await ensure_requested_languages(db, course, _snapshot())


def test_generation_can_admit_both_languages_without_changing_legacy_requests():
    document_id = uuid4()
    assert AIGenerateRequest(documents=[document_id]).languages is None
    assert AIGenerateRequest(documents=[document_id], languages=["ru", "kk"]).languages == ["ru", "kk"]
    with pytest.raises(ValidationError):
        AIGenerateRequest(documents=[document_id], language="ru", languages=["kk"])
