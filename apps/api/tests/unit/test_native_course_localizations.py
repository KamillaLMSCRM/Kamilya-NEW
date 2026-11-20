"""The two languages must share identities and one native grading contract."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.modules.ai.schemas import AIGenerateRequest
from app.modules.courses.localization_router import course_languages, generate_language
from app.modules.courses.localizations import (
    POLICY_KEY,
    ensure_requested_languages,
    source_fields,
    unchanged_translations,
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


def test_revision_carries_only_translations_for_unchanged_mapped_fields():
    new = {"lesson.new.title": "Срок хранения", "lesson.new.content": "Храните 15 дней.",
           "choice.new_choice.text": "15", "lesson.other.title": "Срок хранения"}
    old = {"lesson.old.title": "Срок хранения", "lesson.old.content": "Храните 3 дня.",
           "choice.old_choice.text": "3"}
    translation = {"lesson.old.title": "Сақтау мерзімі", "lesson.old.content": "3 күн сақтаңыз.",
                   "choice.old_choice.text": "3"}
    assert unchanged_translations(new, old, translation, {"new": "old", "new_choice": "old_choice"}) == {
        "lesson.new.title": "Сақтау мерзімі",
    }


@pytest.mark.asyncio
async def test_generates_only_changed_language_fields_and_keeps_the_existing_translations():
    scope = "app.modules.courses.localization_router."
    course = SimpleNamespace(id=uuid4(), source_analysis={
        POLICY_KEY: {"primary": "ru", "requested": ["ru", "kk"]},
    })
    user, db = SimpleNamespace(tenant_id=uuid4()), AsyncMock()
    _, fields = source_fields(_snapshot())
    changed = "question.q.text"
    unchanged = {key: value for key, value in fields.items() if key != changed}
    with (
        patch(scope + "_author_course", return_value=course),
        patch(scope + "author_snapshot", return_value=_snapshot()),
        patch(scope + "carried_editions", return_value={"kk": unchanged}),
        patch(scope + "editions", return_value=[]),
        patch(scope + "save_edition", return_value=True),
        patch(scope + "_set_tenant_security_context", new_callable=AsyncMock),
        patch(scope + "translate_fields", return_value={changed: "Неше позиция бар?"}) as provider,
        patch(scope + "finish_edition_generation", return_value=True),
    ):
        result = await generate_language(course.id, "kk", db, user)
    provider.assert_awaited_once_with({changed: fields[changed]}, "kk", user.tenant_id)
    assert result == {"content": {**unchanged, changed: "Неше позиция бар?"}, "pending": False}


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
