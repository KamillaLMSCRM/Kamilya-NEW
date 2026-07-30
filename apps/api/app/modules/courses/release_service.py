"""Build and persist immutable course publication snapshots."""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.modules.courses.models import Course
from app.modules.courses.release_models import ContentRelease
from app.modules.lessons.models import ContentBlock, Lesson, Module
from app.modules.quizzes.models import Question, Quiz, QuizChoice
from app.modules.scorm.models import ScormPackage


def canonical_json_sha256(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _uuid_strings(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    return sorted({str(value) for value in values if value})


async def build_course_release_snapshot(
    db: AsyncSession,
    course: Course,
    *,
    version: int,
) -> dict[str, Any]:
    modules = (
        await db.execute(
            select(Module)
            .where(Module.course_id == course.id, Module.tenant_id == course.tenant_id)
            .order_by(Module.order_index, Module.id)
        )
    ).scalars().all()
    module_ids = [module.id for module in modules]

    lessons = []
    if module_ids:
        lessons = (
            await db.execute(
                select(Lesson)
                .where(
                    Lesson.module_id.in_(module_ids),
                    Lesson.tenant_id == course.tenant_id,
                )
                .order_by(Lesson.module_id, Lesson.order_index, Lesson.id)
            )
        ).scalars().all()
    lesson_ids = [lesson.id for lesson in lessons]

    blocks = []
    quizzes = []
    if lesson_ids:
        blocks = (
            await db.execute(
                select(ContentBlock)
                .where(ContentBlock.lesson_id.in_(lesson_ids))
                .order_by(ContentBlock.lesson_id, ContentBlock.order_index, ContentBlock.id)
            )
        ).scalars().all()
        quizzes = (
            await db.execute(
                select(Quiz)
                .where(
                    Quiz.lesson_id.in_(lesson_ids),
                    Quiz.tenant_id == course.tenant_id,
                )
                .order_by(Quiz.lesson_id, Quiz.created_at, Quiz.id)
            )
        ).scalars().all()

    quiz_ids = [quiz.id for quiz in quizzes]
    questions = []
    if quiz_ids:
        questions = (
            await db.execute(
                select(Question)
                .where(Question.quiz_id.in_(quiz_ids))
                .order_by(Question.quiz_id, Question.order_index, Question.id)
            )
        ).scalars().all()
    question_ids = [question.id for question in questions]

    choices = []
    if question_ids:
        choices = (
            await db.execute(
                select(QuizChoice)
                .where(QuizChoice.question_id.in_(question_ids))
                .order_by(QuizChoice.question_id, QuizChoice.order_index, QuizChoice.id)
            )
        ).scalars().all()

    blocks_by_lesson: dict[UUID, list[ContentBlock]] = {}
    for block in blocks:
        blocks_by_lesson.setdefault(block.lesson_id, []).append(block)
    quizzes_by_lesson: dict[UUID, list[Quiz]] = {}
    for quiz in quizzes:
        quizzes_by_lesson.setdefault(quiz.lesson_id, []).append(quiz)
    questions_by_quiz: dict[UUID, list[Question]] = {}
    for question in questions:
        questions_by_quiz.setdefault(question.quiz_id, []).append(question)
    choices_by_question: dict[UUID, list[QuizChoice]] = {}
    for choice in choices:
        choices_by_question.setdefault(choice.question_id, []).append(choice)
    lessons_by_module: dict[UUID, list[Lesson]] = {}
    for lesson in lessons:
        lessons_by_module.setdefault(lesson.module_id, []).append(lesson)

    document_ids = set(_uuid_strings(course.source_document_ids))
    if course.source_instruction_id:
        document_ids.add(str(course.source_instruction_id))
    for lesson in lessons:
        document_ids.update(_uuid_strings(lesson.source_document_ids))

    documents = []
    if document_ids:
        parsed_ids = []
        for document_id in document_ids:
            try:
                parsed_ids.append(UUID(document_id))
            except ValueError:
                continue
        if parsed_ids:
            documents = (
                await db.execute(
                    select(Document)
                    .where(
                        Document.id.in_(parsed_ids),
                        Document.tenant_id == course.tenant_id,
                    )
                    .order_by(Document.source_family_id, Document.version, Document.id)
                )
            ).scalars().all()

    scorm_packages = (
        await db.execute(
            select(ScormPackage)
            .where(
                ScormPackage.course_id == course.id,
                ScormPackage.tenant_id == course.tenant_id,
            )
            .order_by(ScormPackage.created_at, ScormPackage.id)
        )
    ).scalars().all()

    def choice_payload(choice: QuizChoice) -> dict[str, Any]:
        return {
            "id": str(choice.id),
            "text": choice.text,
            "is_correct": bool(choice.is_correct),
            "order_index": choice.order_index,
        }

    def question_payload(question: Question) -> dict[str, Any]:
        return {
            "id": str(question.id),
            "text": question.text,
            "type": question.type,
            "points": question.points,
            "explanation": question.explanation,
            "order_index": question.order_index,
            "pool_group": question.pool_group,
            "choices": [
                choice_payload(choice)
                for choice in choices_by_question.get(question.id, [])
            ],
        }

    def quiz_payload(quiz: Quiz) -> dict[str, Any]:
        return {
            "id": str(quiz.id),
            "title": quiz.title,
            "pass_score": quiz.pass_score,
            "time_limit": quiz.time_limit,
            "attempt_limit": quiz.attempt_limit,
            "deferral_days": quiz.deferral_days,
            "questions": [
                question_payload(question)
                for question in questions_by_quiz.get(quiz.id, [])
            ],
        }

    def lesson_payload(lesson: Lesson) -> dict[str, Any]:
        return {
            "id": str(lesson.id),
            "title": lesson.title,
            "content_type": lesson.content_type,
            "content": lesson.content,
            "duration_seconds": lesson.duration_seconds,
            "order_index": lesson.order_index,
            "source_document_ids": _uuid_strings(lesson.source_document_ids),
            "source_references": lesson.source_references or [],
            "source_validation_status": lesson.source_validation_status,
            "content_blocks": [
                {
                    "id": str(block.id),
                    "block_type": block.block_type,
                    "content": block.content,
                    "metadata": block.metadata_,
                    "order_index": block.order_index,
                }
                for block in blocks_by_lesson.get(lesson.id, [])
            ],
            "quizzes": [
                quiz_payload(quiz)
                for quiz in quizzes_by_lesson.get(lesson.id, [])
            ],
        }

    return {
        "schema_version": 1,
        "release_version": version,
        "course": {
            "id": str(course.id),
            "tenant_id": str(course.tenant_id),
            "title": course.title,
            "description": course.description,
            "delivery_type": course.delivery_type,
            "ai_generated": bool(course.ai_generated),
            "source_instruction_id": (
                str(course.source_instruction_id)
                if course.source_instruction_id
                else None
            ),
            "source_instruction_version_at": (
                course.source_instruction_version_at.isoformat()
                if course.source_instruction_version_at
                else None
            ),
            "source_document_ids": _uuid_strings(course.source_document_ids),
            "source_strategy": course.source_strategy,
            "source_combination_goal": course.source_combination_goal,
            "source_analysis": course.source_analysis or {},
            "review_status": course.review_status,
            "reviewed_by": str(course.reviewed_by) if course.reviewed_by else None,
            "reviewed_at": (
                course.reviewed_at.isoformat() if course.reviewed_at else None
            ),
            "review_comment": course.review_comment,
        },
        "source_documents": [
            {
                "id": str(document.id),
                "source_family_id": str(document.source_family_id),
                "version": document.version,
                "title": document.title,
                "filename": document.filename,
                "category": document.category,
                "content_type": document.content_type,
                "file_size": document.size,
                "content_sha256": document.content_sha256,
            }
            for document in documents
        ],
        "modules": [
            {
                "id": str(module.id),
                "title": module.title,
                "description": module.description,
                "order_index": module.order_index,
                "lessons": [
                    lesson_payload(lesson)
                    for lesson in lessons_by_module.get(module.id, [])
                ],
            }
            for module in modules
        ],
        "scorm_packages": [
            {
                "id": str(package.id),
                "version": package.version,
                "title": package.title,
                "entrypoint": package.entrypoint,
                "original_filename": (package.manifest_json or {}).get(
                    "original_filename"
                ),
                "content_sha256": (package.manifest_json or {}).get("sha256"),
            }
            for package in scorm_packages
        ],
    }


async def create_course_release(
    db: AsyncSession,
    course: Course,
    *,
    published_by: UUID | None,
) -> ContentRelease:
    latest_version = await db.scalar(
        select(func.max(ContentRelease.version)).where(
            ContentRelease.course_id == course.id,
            ContentRelease.tenant_id == course.tenant_id,
        )
    )
    version = int(latest_version or 0) + 1
    snapshot = await build_course_release_snapshot(db, course, version=version)
    release = ContentRelease(
        tenant_id=course.tenant_id,
        course_id=course.id,
        version=version,
        snapshot=snapshot,
        snapshot_sha256=canonical_json_sha256(snapshot),
        published_by=published_by,
    )
    db.add(release)
    await db.flush()
    course.current_release_id = release.id
    await db.flush()
    return release
