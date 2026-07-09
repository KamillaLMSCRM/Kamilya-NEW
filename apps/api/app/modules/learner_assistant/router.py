from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user, require_tenant_user
from app.core.db import get_db
from app.models.courses import Course
from app.models.enrollment import Enrollment
from app.models.users import User
from app.modules.ai.llm_client import ResilientLLMClient
from app.modules.learner_assistant.models import LearnerAssistantMessage
from app.modules.learner_assistant.schemas import (
    LearnerAssistantChatRequest,
    LearnerAssistantChatResponse,
    LearnerAssistantMessageResponse,
)
from app.modules.lessons.models import Lesson, Module

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/learner/assistant",
    tags=["learner-assistant"],
    dependencies=[Depends(require_tenant_user())],
)


async def _assert_course_access(db: AsyncSession, course_id: UUID, user: User) -> Course:
    result = await db.execute(
        select(Course).where(Course.id == course_id, Course.tenant_id == user.tenant_id)
    )
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    if user.role in {"admin", "org_admin", "teacher", "methodologist", "superadmin"}:
        return course
    enrolled = await db.scalar(
        select(Enrollment.id).where(
            Enrollment.course_id == course_id,
            Enrollment.user_id == user.id,
            Enrollment.tenant_id == user.tenant_id,
        )
    )
    if not enrolled:
        raise HTTPException(status_code=403, detail="Course is not assigned to this learner")
    return course


async def _build_context(db: AsyncSession, course: Course, lesson_id: UUID | None, tenant_id: UUID) -> tuple[str, list[str]]:
    sources = [f"Курс: {course.title}"]
    lines = [
        f"Курс: {course.title}",
        f"Описание курса: {course.description or '(нет описания)'}",
    ]
    if lesson_id:
        lesson = await db.get(Lesson, lesson_id)
        if not lesson or lesson.tenant_id != tenant_id:
            raise HTTPException(status_code=404, detail="Lesson not found")
        module = await db.get(Module, lesson.module_id)
        if not module or module.course_id != course.id:
            raise HTTPException(status_code=404, detail="Lesson is not part of this course")
        sources.append(f"Урок: {lesson.title}")
        lines.extend([
            f"Модуль: {module.title}",
            f"Текущий урок: {lesson.title}",
            "",
            "Материал урока:",
            (lesson.content or "")[:7000],
        ])
    else:
        modules_q = await db.execute(
            select(Module).where(Module.course_id == course.id).order_by(Module.order_index)
        )
        modules = modules_q.scalars().all()
        for module in modules[:6]:
            lessons_q = await db.execute(
                select(Lesson).where(Lesson.module_id == module.id).order_by(Lesson.order_index)
            )
            lessons = lessons_q.scalars().all()
            lines.append(f"Модуль: {module.title}")
            for lesson in lessons[:8]:
                lines.append(f"- {lesson.title}: {(lesson.content or '')[:450]}")
    return "\n".join(lines), sources


@router.get("/messages", response_model=list[LearnerAssistantMessageResponse])
async def list_messages(
    course_id: UUID = Query(...),
    lesson_id: UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _assert_course_access(db, course_id, user)
    stmt = (
        select(LearnerAssistantMessage)
        .where(
            LearnerAssistantMessage.tenant_id == user.tenant_id,
            LearnerAssistantMessage.user_id == user.id,
            LearnerAssistantMessage.course_id == course_id,
        )
        .order_by(LearnerAssistantMessage.created_at.asc())
        .limit(60)
    )
    if lesson_id:
        stmt = stmt.where(LearnerAssistantMessage.lesson_id == lesson_id)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("/chat", response_model=LearnerAssistantChatResponse)
async def learner_chat(
    req: LearnerAssistantChatRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    course = await _assert_course_access(db, req.course_id, user)
    context, sources = await _build_context(db, course, req.lesson_id, user.tenant_id)

    system_prompt = (
        "Ты AI-ассистент обучающегося в корпоративной LMS Kamilya. "
        "Отвечай кратко, понятно и только по материалам курса ниже. "
        "Если в материалах нет ответа, честно скажи, что в текущем уроке этого нет. "
        "Не давай прямые ответы на тестовые вопросы и не выбирай варианты за обучающегося. "
        "Вместо этого объясняй принцип, термин или где перечитать материал. "
        "Пиши на языке вопроса обучающегося."
    )
    user_prompt = (
        f"Материалы курса:\n{context}\n\n"
        f"Вопрос обучающегося:\n{req.message}"
    )

    db.add(LearnerAssistantMessage(
        tenant_id=user.tenant_id,
        user_id=user.id,
        course_id=req.course_id,
        lesson_id=req.lesson_id,
        role="user",
        content=req.message,
    ))

    llm = await ResilientLLMClient.from_settings_async(temperature=0.2, max_tokens=900)
    try:
        resp = await llm.ainvoke([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ])
        reply = (resp.content or "").strip() or "Не получилось сформировать ответ."
    except Exception as e:
        logger.error("Learner assistant failed: %s", e, exc_info=True)
        raise HTTPException(status_code=502, detail="AI assistant is unavailable, try again")

    db.add(LearnerAssistantMessage(
        tenant_id=user.tenant_id,
        user_id=user.id,
        course_id=req.course_id,
        lesson_id=req.lesson_id,
        role="assistant",
        content=reply,
    ))
    await db.commit()
    return {"reply": reply, "sources": sources}
