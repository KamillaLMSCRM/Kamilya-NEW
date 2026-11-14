"""Read-only, tenant-owned editorial context. No inference or vector retrieval."""

from __future__ import annotations

import asyncio
import json
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.modules.courses.models import Course
from app.modules.lessons.models import Lesson, Module
from app.modules.quizzes.models import Question, Quiz, QuizChoice


async def source_context(db: AsyncSession, course: Course, tenant_id: UUID) -> dict[str, Any]:
    """Use the edition that produced this course, never silently the latest one."""
    from app.modules.source_editorial_review.domain import SOURCE_PINS
    from app.modules.source_editorial_review.service import resolve_pins

    raw_ids = cast(list[Any], course.source_document_ids or [])
    if not raw_ids and course.source_instruction_id:
        raw_ids = [str(course.source_instruction_id)]
    try:
        ids = [UUID(str(value)) for value in raw_ids]
        if len(set(ids)) != len(ids):
            raise ValueError
    except (ValueError, TypeError):
        return {"status": "unavailable", "reason": "invalid_source_binding", "documents": []}
    if not ids:
        return {"status": "unavailable", "reason": "no_linked_sources", "documents": []}
    documents = list((await db.scalars(select(Document).where(
        Document.id.in_(ids), Document.tenant_id == tenant_id,
        Document.lifecycle_status == "active",
    ).order_by(Document.id))).all())
    if {document.id for document in documents} != set(ids):
        return {"status": "unavailable", "reason": "linked_source_unavailable", "documents": []}
    analysis: dict[str, Any] = course.source_analysis if isinstance(course.source_analysis, dict) else {}
    if SOURCE_PINS not in analysis:
        # Reading an arbitrary current blob could substitute a newer revision,
        # run OCR, or lose approved visual/part context. Do not manufacture it.
        return {"status": "unavailable", "reason": "source_edition_not_pinned", "documents": []}
    try:
        async with asyncio.timeout(30):
            approved = await resolve_pins(db, tenant_id, [str(value) for value in ids], analysis[SOURCE_PINS])
    except (TimeoutError, ValueError, RuntimeError):
        return {"status": "unavailable", "reason": "pinned_source_unavailable", "documents": []}
    return {"status": "complete", "documents": [
        {"document_id": str(document.id), "title": document.title,
         "approval_id": approved[str(document.id)].approval_id,
         "source_revision": approved[str(document.id)].source_revision,
         "working_sha256": approved[str(document.id)].working_sha256,
         "text": approved[str(document.id)].working_text}
        for document in documents
    ]}


async def load_course_context(
    db: AsyncSession, course_id: UUID, tenant_id: UUID, *, include_sources: bool = True,
) -> str:
    course = await db.scalar(select(Course).where(Course.id == course_id, Course.tenant_id == tenant_id))
    if course is None:
        return ""
    if not include_sources:
        return str(course.title)  # Refusal ownership check must never resolve sources.
    modules = list((await db.scalars(select(Module).where(
        Module.course_id == course_id, Module.tenant_id == tenant_id,
    ).order_by(Module.order_index, Module.id))).all())
    lessons = list((await db.scalars(select(Lesson).join(Module, Module.id == Lesson.module_id).where(
        Module.course_id == course_id, Module.tenant_id == tenant_id, Lesson.tenant_id == tenant_id,
    ).order_by(Module.order_index, Lesson.order_index, Lesson.id))).all())
    lesson_ids = [lesson.id for lesson in lessons]
    quizzes = list((await db.scalars(select(Quiz).where(
        Quiz.lesson_id.in_(lesson_ids), Quiz.tenant_id == tenant_id,
    ).order_by(Quiz.id))).all()) if lesson_ids else []
    quiz_ids = [quiz.id for quiz in quizzes]
    questions = list((await db.scalars(select(Question).join(Quiz, Quiz.id == Question.quiz_id).where(
        Quiz.id.in_(quiz_ids), Quiz.tenant_id == tenant_id,
    ).order_by(Question.order_index, Question.id))).all()) if quiz_ids else []
    choices = list((await db.scalars(select(QuizChoice).join(Question, Question.id == QuizChoice.question_id)
        .join(Quiz, Quiz.id == Question.quiz_id).where(Quiz.id.in_(quiz_ids), Quiz.tenant_id == tenant_id)
        .order_by(QuizChoice.order_index, QuizChoice.id))).all()) if questions else []
    body = {
        "sources": await source_context(db, course, tenant_id),
        "course": {"id": str(course.id), "title": course.title, "description": course.description,
                   "status": course.status, "review_status": course.review_status},
        "modules": [{"id": str(module.id), "title": module.title,
            "lessons": [{"id": str(lesson.id), "title": lesson.title, "content_type": lesson.content_type,
                "text": lesson.content or "", "source_references": lesson.source_references or [],
                "quizzes": [{"id": str(quiz.id), "title": quiz.title, "review_status": quiz.review_status,
                    "questions": [{"id": str(question.id), "text": question.text, "type": question.type,
                        "explanation": question.explanation, "source_quote": question.source_quote,
                        "choices": [{"id": str(choice.id), "text": choice.text, "is_correct": choice.is_correct}
                            for choice in choices if choice.question_id == question.id]}
                        for question in questions if question.quiz_id == quiz.id]}
                    for quiz in quizzes if quiz.lesson_id == lesson.id]}
                for lesson in lessons if lesson.module_id == module.id]}
            for module in modules],
    }
    return json.dumps(body, ensure_ascii=False, separators=(",", ":"))
