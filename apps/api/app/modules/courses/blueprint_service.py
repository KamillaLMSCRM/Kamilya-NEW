"""Deep module for blueprint discovery, instantiation and safe adaptation."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.models.tenants import Tenant
from app.modules.courses.blueprint_catalog import (
    FINANCE_IS_BLUEPRINT_ID,
    get_blueprint,
    list_blueprints,
)
from app.modules.courses.blueprint_schemas import (
    BlueprintAdaptationSnapshot,
    BlueprintChecklistItemResponse,
    BlueprintInstantiationRequest,
    BlueprintInstantiationResponse,
    CourseBlueprintResponse,
)
from app.modules.courses.models import Course
from app.modules.lessons.models import Lesson, Module
from app.modules.quizzes.models import Question, Quiz, QuizChoice


@dataclass(frozen=True)
class BlueprintAlreadyInstantiatedError(Exception):
    course_id: UUID


@dataclass(frozen=True)
class BlueprintNotFoundError(Exception):
    blueprint_id: str


@dataclass(frozen=True)
class BlueprintSourceDocumentError(Exception):
    missing_document_ids: tuple[UUID, ...]


@dataclass(frozen=True)
class BlueprintContentConflictError(Exception):
    message: str


def _sha256_text(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _catalog_response(blueprint: dict[str, Any]) -> CourseBlueprintResponse:
    question_count = sum(len(lesson["questions"]) for lesson in blueprint["lessons"])
    return CourseBlueprintResponse(
        id=blueprint["id"],
        version=blueprint["version"],
        locale=blueprint["locale"],
        title=blueprint["title"],
        description=blueprint["description"],
        audience=blueprint["audience"],
        estimated_ready_percent=blueprint["estimated_ready_percent"],
        customization_percent=blueprint["customization_percent"],
        module_count=1,
        lesson_count=len(blueprint["lessons"]),
        quiz_question_count=question_count,
        checklist=[
            BlueprintChecklistItemResponse(**{key: value for key, value in item.items() if key != "lesson_id"})
            for item in blueprint["checklist"]
        ],
        limitations=blueprint["limitations"],
    )


def get_catalog(locale: str) -> list[CourseBlueprintResponse]:
    return [_catalog_response(item) for item in list_blueprints(locale)]


def get_catalog_item(blueprint_id: str, locale: str) -> CourseBlueprintResponse:
    if blueprint_id != FINANCE_IS_BLUEPRINT_ID:
        raise BlueprintNotFoundError(blueprint_id)
    return _catalog_response(get_blueprint(locale))


def calculate_adaptation(blueprint: dict[str, Any], answers: dict[str, str]) -> tuple[int, list[str], list[str]]:
    allowed_ids = [item["id"] for item in blueprint["checklist"]]
    unknown = set(answers) - set(allowed_ids)
    if unknown:
        raise ValueError(f"Unknown adaptation items: {', '.join(sorted(unknown))}")
    completed = [item_id for item_id in allowed_ids if answers.get(item_id, "").strip()]
    missing = [item_id for item_id in allowed_ids if item_id not in completed]
    customization = blueprint["customization_percent"]
    readiness = blueprint["estimated_ready_percent"] + round(customization * len(completed) / len(allowed_ids))
    return min(100, readiness), completed, missing


def _render_lesson(
    blueprint: dict[str, Any],
    lesson: dict[str, Any],
    answers: dict[str, str],
) -> str:
    parts = [f"# {lesson['title']}", *lesson["content"]]
    additions = [
        (item["title"], answers[item["id"]])
        for item in blueprint["checklist"]
        if item["lesson_id"] == lesson["id"] and answers.get(item["id"])
    ]
    missing = [
        item for item in blueprint["checklist"] if item["lesson_id"] == lesson["id"] and not answers.get(item["id"])
    ]
    if additions or missing:
        parts.append(f"## {blueprint['custom_heading']}")
        parts.extend(f"**{title}:** {answer}" for title, answer in additions)
        parts.extend(f"> {item['title']}: {item['answer_placeholder']}" for item in missing)
    return "\n\n".join(parts)


def _build_analysis(
    blueprint: dict[str, Any],
    answers: dict[str, str],
    source_document_ids: list[UUID],
    render_state: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    readiness, completed, missing = calculate_adaptation(blueprint, answers)
    return {
        "blueprint": {
            "id": blueprint["id"],
            "version": blueprint["version"],
            "locale": blueprint["locale"],
            "estimated_ready_percent": blueprint["estimated_ready_percent"],
            "customization_percent": blueprint["customization_percent"],
        },
        "adaptation": {
            "readiness_percent": readiness,
            "answers": dict(answers),
            "source_document_ids": [str(item) for item in source_document_ids],
            "completed_checklist_items": completed,
            "missing_checklist_items": missing,
        },
        "render_state": render_state or {},
    }


def adaptation_snapshot(course: Course) -> BlueprintAdaptationSnapshot:
    analysis: dict[str, Any] = dict(course.source_analysis or {})
    marker = analysis.get("blueprint") or {}
    adaptation = analysis.get("adaptation") or {}
    if marker.get("id") != FINANCE_IS_BLUEPRINT_ID:
        raise BlueprintNotFoundError(str(marker.get("id") or ""))
    return BlueprintAdaptationSnapshot(
        blueprint_id=marker["id"],
        blueprint_version=marker["version"],
        locale=marker["locale"],
        readiness_percent=adaptation.get("readiness_percent", 70),
        answers=dict(adaptation.get("answers") or {}),
        source_document_ids=[UUID(value) for value in adaptation.get("source_document_ids") or []],
        completed_checklist_items=list(adaptation.get("completed_checklist_items") or []),
        missing_checklist_items=list(adaptation.get("missing_checklist_items") or []),
    )


def assert_blueprint_ready_for_approval(course: Course) -> None:
    analysis: dict[str, Any] = dict(course.source_analysis or {})
    marker = analysis.get("blueprint") or {}
    if not marker:
        return
    snapshot = adaptation_snapshot(course)
    if snapshot.readiness_percent < 100 or snapshot.missing_checklist_items:
        raise BlueprintContentConflictError("Complete the organization-specific adaptation checklist before approval")


async def _validate_documents(
    db: AsyncSession,
    tenant_id: UUID,
    document_ids: list[UUID],
) -> None:
    if not document_ids:
        return
    rows = (
        (
            await db.execute(
                select(Document.id).where(
                    Document.tenant_id == tenant_id,
                    Document.id.in_(document_ids),
                    Document.lifecycle_status == "active",
                )
            )
        )
        .scalars()
        .all()
    )
    found = set(rows)
    missing = tuple(document_id for document_id in document_ids if document_id not in found)
    if missing:
        raise BlueprintSourceDocumentError(missing)


def _response(course: Course) -> BlueprintInstantiationResponse:
    snapshot = adaptation_snapshot(course)
    return BlueprintInstantiationResponse(
        course_id=course.id,
        blueprint_id=snapshot.blueprint_id,
        blueprint_version=snapshot.blueprint_version,
        locale=snapshot.locale,
        readiness_percent=snapshot.readiness_percent,
        completed_checklist_items=snapshot.completed_checklist_items,
        missing_checklist_items=snapshot.missing_checklist_items,
        edit_url=f"/courses/{course.id}/edit",
        adaptation_url=f"/courses/templates/{snapshot.blueprint_id}?course_id={course.id}",
    )


async def instantiate_blueprint(
    db: AsyncSession,
    *,
    blueprint_id: str,
    tenant_id: UUID,
    user_id: UUID,
    request: BlueprintInstantiationRequest,
) -> tuple[Course, BlueprintInstantiationResponse]:
    if blueprint_id != FINANCE_IS_BLUEPRINT_ID:
        raise BlueprintNotFoundError(blueprint_id)
    blueprint = get_blueprint(request.locale)
    calculate_adaptation(blueprint, request.answers)
    await _validate_documents(db, tenant_id, request.source_document_ids)

    tenant = (await db.execute(select(Tenant).where(Tenant.id == tenant_id).with_for_update())).scalar_one_or_none()
    if tenant is None:
        raise BlueprintNotFoundError(blueprint_id)

    existing_courses = (
        (
            await db.execute(
                select(Course).where(
                    Course.tenant_id == tenant_id,
                    Course.status != "archived",
                )
            )
        )
        .scalars()
        .all()
    )
    for existing in existing_courses:
        marker = (existing.source_analysis or {}).get("blueprint") or {}
        if (
            marker.get("id") == blueprint_id
            and marker.get("version") == blueprint["version"]
            and marker.get("locale") == request.locale
        ):
            raise BlueprintAlreadyInstantiatedError(existing.id)

    course = Course(
        tenant_id=tenant_id,
        title=request.title or blueprint["title"],
        description=blueprint["description"],
        status="draft",
        delivery_type="native",
        created_by=user_id,
        ai_generated=False,
        source_document_ids=[str(value) for value in request.source_document_ids],
        source_strategy="single_topic",
        source_analysis=_build_analysis(
            blueprint,
            request.answers,
            request.source_document_ids,
        ),
        review_status="pending",
    )
    db.add(course)
    await db.flush()

    module = Module(
        tenant_id=tenant_id,
        course_id=course.id,
        title=blueprint["module_title"],
        description=blueprint["module_description"],
        order_index=0,
        ai_generated=False,
    )
    db.add(module)
    await db.flush()

    render_state: dict[str, dict[str, str]] = {}
    for lesson_index, lesson_blueprint in enumerate(blueprint["lessons"]):
        content = _render_lesson(blueprint, lesson_blueprint, request.answers)
        lesson = Lesson(
            tenant_id=tenant_id,
            module_id=module.id,
            title=lesson_blueprint["title"],
            content_type="text",
            content=content,
            duration_seconds=300,
            order_index=lesson_index,
            ai_generated=False,
            source_document_ids=[str(value) for value in request.source_document_ids],
            source_validation_status="needs_review",
        )
        db.add(lesson)
        await db.flush()
        render_state[str(lesson.id)] = {
            "blueprint_lesson_id": lesson_blueprint["id"],
            "content_sha256": _sha256_text(content),
        }

        quiz = Quiz(
            tenant_id=tenant_id,
            lesson_id=lesson.id,
            title=f"{lesson_blueprint['title']}: проверка"
            if request.locale == "ru"
            else f"{lesson_blueprint['title']}: тексеру",
            pass_score=80,
            attempt_limit=3,
            deferral_days=7,
        )
        db.add(quiz)
        await db.flush()
        for question_index, (question_text, choices, correct_index, explanation) in enumerate(
            lesson_blueprint["questions"]
        ):
            question = Question(
                quiz_id=quiz.id,
                text=question_text,
                type="single_choice",
                points=1,
                explanation=explanation,
                order_index=question_index,
            )
            db.add(question)
            await db.flush()
            for choice_index, choice_text in enumerate(choices):
                db.add(
                    QuizChoice(
                        question_id=question.id,
                        text=choice_text,
                        is_correct=choice_index == correct_index,
                        order_index=choice_index,
                    )
                )

    course.source_analysis = _build_analysis(
        blueprint,
        request.answers,
        request.source_document_ids,
        render_state,
    )
    await db.flush()
    return course, _response(course)


async def update_blueprint_adaptation(
    db: AsyncSession,
    *,
    course: Course,
    request: BlueprintInstantiationRequest,
) -> BlueprintInstantiationResponse:
    if course.status != "draft":
        raise BlueprintContentConflictError("Only a draft blueprint course can be adapted")
    snapshot = adaptation_snapshot(course)
    if snapshot.blueprint_version != get_blueprint(snapshot.locale)["version"]:
        raise BlueprintContentConflictError("This blueprint version is no longer editable")
    if request.locale != snapshot.locale:
        raise BlueprintContentConflictError("Blueprint locale cannot be changed after instantiation")

    blueprint = get_blueprint(snapshot.locale)
    calculate_adaptation(blueprint, request.answers)
    await _validate_documents(db, course.tenant_id, request.source_document_ids)
    previous_state = dict((course.source_analysis or {}).get("render_state") or {})
    lesson_rows = (
        (
            await db.execute(
                select(Lesson)
                .join(Module, Module.id == Lesson.module_id)
                .where(
                    Module.course_id == course.id,
                    Module.tenant_id == course.tenant_id,
                    Lesson.tenant_id == course.tenant_id,
                )
            )
        )
        .scalars()
        .all()
    )
    lessons_by_id = {str(lesson.id): lesson for lesson in lesson_rows}
    if set(lessons_by_id) != set(previous_state):
        raise BlueprintContentConflictError("Course structure changed; continue adaptation in the course editor")
    blueprint_lessons = {item["id"]: item for item in blueprint["lessons"]}
    next_state: dict[str, dict[str, str]] = {}
    for lesson_id, state in previous_state.items():
        lesson = lessons_by_id[lesson_id]
        if _sha256_text(lesson.content or "") != state.get("content_sha256"):
            raise BlueprintContentConflictError(
                "Course content was edited manually; continue adaptation in the course editor"
            )
        lesson_blueprint = blueprint_lessons[state["blueprint_lesson_id"]]
        next_content = _render_lesson(blueprint, lesson_blueprint, request.answers)
        lesson.content = next_content
        lesson.source_document_ids = [str(value) for value in request.source_document_ids]
        lesson.source_validation_status = "needs_review"
        next_state[lesson_id] = {
            "blueprint_lesson_id": lesson_blueprint["id"],
            "content_sha256": _sha256_text(next_content),
        }

    course.title = request.title or course.title
    course.source_document_ids = [str(value) for value in request.source_document_ids]
    course.source_analysis = _build_analysis(
        blueprint,
        request.answers,
        request.source_document_ids,
        next_state,
    )
    course.review_status = "pending"
    course.reviewed_by = None
    course.reviewed_at = None
    course.review_comment = None
    await db.flush()
    return _response(course)
