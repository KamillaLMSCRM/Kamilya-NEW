"""AI Generation — API router with WebSocket progress."""
from __future__ import annotations

import asyncio
import json
import logging
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, Query
from uuid import UUID, uuid4
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth import get_current_user, decode_token, require_role, require_tenant_user
from app.core.db import get_db
from app.models.users import User
from app.modules.ai.schemas import (
    AIGenerateRequest,
    AIJobResponse,
    AIChatRequest,
    AIChatResponse,
    AIRegenerateModuleRequest,
    AIRegenerateLessonRequest,
)
from app.modules.ai.job_service import create_ai_job, get_ai_job, update_ai_job
from app.modules.ai.pipeline import run_generation_pipeline
from app.modules.ai.llm_client import ResilientLLMClient, create_llm
from app.modules.courses.models import Course
from app.ml_prompts import get_renderer

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/ai",
    tags=["ai-generation"],
    dependencies=[Depends(require_tenant_user())],
)

# Store running tasks for cancellation
_running_tasks: dict[str, asyncio.Task] = {}


@router.post("/generate-course", response_model=AIJobResponse, status_code=202)
async def generate_course(
    req: AIGenerateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Start AI course generation (returns job_id for polling/WebSocket)."""
    from app.core.demo_limits import check_ai_generation_quota
    await check_ai_generation_quota(db, user.id, user.tenant_id)

    # Per-tenant LLM cost gate (audit §6.3). Raises 429 if monthly
    # budget exceeded. Default budget is $50/month per tenant; see
    # tenant_settings.monthly_llm_budget_usd_cents.
    from app.modules.ai.budget import check_and_charge_llm_budget
    if user.tenant_id:
        await check_and_charge_llm_budget(
            db, str(user.tenant_id), operation="generate_course",
        )

    job = await create_ai_job(
        db=db,
        tenant_id=user.tenant_id,
        user_id=user.id,
        course_id=req.course_id,
        params={
            "documents": req.documents,
            "target_audience": req.target_audience,
            "num_modules": req.num_modules,
            "language": req.language,
        },
    )
    await db.commit()

    # Run pipeline directly as background task (no Celery needed)
    async def _safe_pipeline():
        from app.core.db import async_session_factory
        try:
            logger.info(f"Starting generation pipeline for job {job.id}")
            await run_generation_pipeline(
                job_id=job.id,
                documents=req.documents,
                target_audience=req.target_audience,
                num_modules=req.num_modules,
                language=req.language,
                course_id=str(req.course_id) if req.course_id else None,
                tenant_id=user.tenant_id,
                user_id=user.id,
            )
            logger.info(f"Pipeline completed for job {job.id}")
        except asyncio.CancelledError:
            logger.info(f"Pipeline cancelled for job {job.id}")
            async with async_session_factory() as session:
                await update_ai_job(session, job.id, tenant_id=user.tenant_id, status="cancelled", message="Cancelled by user")
                await session.commit()
        except Exception as e:
            logger.error(f"Pipeline failed for job {job.id}: {e}", exc_info=True)
        finally:
            _running_tasks.pop(job.id, None)

    task = asyncio.create_task(_safe_pipeline())
    _running_tasks[job.id] = task

    return AIJobResponse(
        id=job.id,
        status="pending",
        course_id=req.course_id,
        created_at=job.created_at,
        progress=0,
        stage="queued",
        message="Job queued",
    )


@router.get("/jobs", response_model=list[AIJobResponse])
async def list_jobs(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List AI jobs for current tenant."""
    from sqlalchemy import select
    from app.models.ai_job import AIJob

    stmt = (
        select(AIJob)
        .where(AIJob.tenant_id == user.tenant_id)
        .order_by(AIJob.created_at.desc())
        .limit(20)
    )
    result = await db.execute(stmt)
    jobs = result.scalars().all()

    return [
        AIJobResponse(
            id=j.id,
            status=j.status,
            course_id=UUID(j.course_id) if j.course_id else None,
            created_at=j.created_at,
            progress=j.progress,
            stage=j.stage,
            message=j.message or "",
        )
        for j in jobs
    ]


@router.get("/jobs/{job_id}", response_model=AIJobResponse)
async def get_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get job status (for polling)."""
    job = await get_ai_job(db, job_id, tenant_id=str(user.tenant_id) if user.tenant_id else None)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return AIJobResponse(
        id=job.id,
        status=job.status,
        course_id=UUID(job.course_id) if job.course_id else None,
        created_at=job.created_at,
        progress=job.progress,
        stage=job.stage,
        message=job.message or "",
    )


@router.post("/jobs/{job_id}/cancel")
async def cancel_generation(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Cancel a running generation job."""
    job = await get_ai_job(db, job_id, tenant_id=str(user.tenant_id) if user.tenant_id else None)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status in ("completed", "failed", "cancelled"):
        raise HTTPException(status_code=400, detail="Job already finished")

    # Cancel the actual asyncio task
    task = _running_tasks.get(job_id)
    if task and not task.done():
        task.cancel()
        logger.info(f"Cancelled task for job {job_id}")
    else:
        # Task not found in memory (server restarted), just update DB
        await update_ai_job(db, job_id, tenant_id=str(user.tenant_id) if user.tenant_id else None, status="cancelled", message="Cancelled by user")
        await db.commit()

    return {"status": "cancelled"}


@router.websocket("/ws/jobs/{job_id}")
async def job_progress_ws(websocket: WebSocket, job_id: str, token: str = Query(None)):
    """WebSocket endpoint for real-time job progress updates. Requires JWT via query param."""
    # Authenticate via token query param
    if not token:
        await websocket.close(code=4001, reason="Missing token")
        return

    try:
        payload = decode_token(token)
    except Exception:
        await websocket.close(code=4003, reason="Invalid token")
        return

    user_id = payload.get("sub")
    tenant_id = payload.get("tenant_id")
    if not user_id or not tenant_id:
        await websocket.close(code=4003, reason="Invalid token payload")
        return

    await websocket.accept()

    try:
        while True:
            from app.core.db import async_session_factory
            async with async_session_factory() as session:
                job = await get_ai_job(session, job_id, tenant_id=str(tenant_id) if tenant_id else None)
                if not job:
                    await websocket.send_json({"error": "Job not found"})
                    break

                # Belt-and-braces: query is already tenant-scoped, but in
                # case the JWT tenant_id is None (superadmin) we accept.
                await websocket.send_json({
                    "job_id": job.id,
                    "status": job.status,
                    "stage": job.stage,
                    "progress": job.progress,
                    "message": job.message or "",
                })

                if job.status in ("completed", "failed", "cancelled"):
                    break

            await asyncio.sleep(2)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_json({"error": str(e)})
        except Exception:
            pass


# ── AI chat assistant (methodologist review) ──────────────────────────────


async def _fetch_course_summary(db: AsyncSession, course_id: UUID, tenant_id: UUID) -> str:
    """Compact course outline (modules → lessons titles + quiz count)."""
    from app.modules.lessons.models import Module, Lesson

    course_q = await db.execute(
        select(Course).where(Course.id == course_id, Course.tenant_id == tenant_id)
    )
    course = course_q.scalar_one_or_none()
    if not course:
        return ""

    modules_q = await db.execute(
        select(Module).where(Module.course_id == course_id).order_by(Module.order_index)
    )
    modules = modules_q.scalars().all()
    lines = [
        f"Курс: {course.title}",
        f"Описание: {course.description or '(пусто)'}",
        f"Статус: {course.status}; review_status: {course.review_status}",
        f"Модулей: {len(modules)}",
    ]
    for m in modules:
        lessons_q = await db.execute(
            select(Lesson).where(Lesson.module_id == m.id).order_by(Lesson.order_index)
        )
        lessons = lessons_q.scalars().all()
        lesson_titles = [f'"{l.title}"' for l in lessons]
        lines.append(f"  Модуль {m.order_index+1}: {m.title} — уроки: {', '.join(lesson_titles) or '(нет)'}")

    return "\n".join(lines)


async def _fetch_target_context(
    db: AsyncSession, course_id: UUID, context: str, target_id: UUID, tenant_id: UUID
) -> str:
    """If the user picked a specific lesson/module as focus, fetch its content."""
    from app.modules.lessons.models import Module, Lesson
    from app.modules.quizzes.models import Quiz

    if context == "module":
        m = await db.get(Module, target_id)
        if not m or m.course_id != course_id or m.tenant_id != tenant_id:
            return ""
        lessons_q = await db.execute(
            select(Lesson).where(Lesson.module_id == m.id).order_by(Lesson.order_index)
        )
        lessons = lessons_q.scalars().all()
        body = [f"Фокус: модуль «{m.title}» (id={target_id})", f"Описание: {m.description or '(пусто)'}"]
        for l in lessons:
            body.append(f"  Урок «{l.title}»:\n{(l.content or '')[:1500]}")
        return "\n".join(body)

    if context == "lesson":
        l = await db.get(Lesson, target_id)
        if not l:
            return ""
        # Verify the lesson belongs to a module of this course
        m = await db.get(Module, l.module_id)
        if not m or m.course_id != course_id or l.tenant_id != tenant_id:
            return ""
        body = [
            f"Фокус: урок «{l.title}» (id={target_id})",
            f"Модуль: {m.title}",
            f"Длительность: {l.duration_seconds or '?'} сек",
            "",
            (l.content or "")[:4000],
        ]
        return "\n".join(body)

    return ""


@router.post("/chat", response_model=AIChatResponse)
async def chat(
    req: AIChatRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Methodologist assistant — short LLM reply grounded in the course.

    NOT a streaming endpoint — we await the full reply and return it.
    Target latency budget: ~6s on a healthy Qwen 3.5.

    Scopes:
    - context='course': assistant gets the whole outline.
    - context='module' or 'lesson': assistant also gets the focus body
      (lesson content truncated to first ~4 KB).
    """
    if req.context in ("module", "lesson") and not req.target_id:
        raise HTTPException(
            status_code=400,
            detail=f"target_id is required when context='{req.context}'",
        )

    summary = await _fetch_course_summary(db, req.course_id, user.tenant_id)
    if not summary:
        raise HTTPException(status_code=404, detail="Course not found")

    target_block = ""
    if req.target_id:
        target_block = await _fetch_target_context(
            db, req.course_id, req.context, req.target_id, user.tenant_id
        )

    system_prompt = get_renderer().render("router/system_methodology_review.md")

    user_block_parts = [f"Контекст курса:\n{summary}"]
    if target_block:
        user_block_parts.append(f"\nФокус рецензии:\n{target_block}")
    user_block_parts.append(f"\nСообщение методолога:\n{req.message}")
    user_block = "\n".join(user_block_parts)

    llm = await ResilientLLMClient.from_settings_async(temperature=0.4, max_tokens=1500)
    try:
        resp = await llm.ainvoke(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_block},
            ]
        )
        reply = (resp.content or "").strip()
    except Exception as e:
        logger.error(f"AI chat LLM call failed: {e}", exc_info=True)
        raise HTTPException(status_code=502, detail="AI assistant is unavailable, try again")

    if not reply:
        reply = "(пустой ответ от модели)"

    # Parse [APPLY_LESSON:UUID]body[/APPLY_LESSON] blocks — extract the first one
    # if present, strip from reply. Pattern is permissive on whitespace.
    import re
    apply_id: UUID | None = None
    apply_content: str | None = None
    apply_title_hint: str | None = None
    m = re.search(
        r"\[APPLY_LESSON:([0-9a-fA-F-]{36})(?:\|title=([^\]]*))?\]([\s\S]*?)\[/APPLY_LESSON\]",
        reply,
        flags=re.DOTALL,
    )
    if m:
        try:
            apply_id = UUID(m.group(1))
            apply_title_hint = m.group(2)
            apply_content = m.group(3).strip()
            # Strip the marker block from the visible reply (the assistant's
            # explanatory text remains; the marker block is just the suggestion payload).
            reply = (reply[: m.start()] + reply[m.end() :]).strip()
        except (ValueError, AttributeError):
            apply_id = None
            apply_content = None

    return AIChatResponse(
        reply=reply or "(пустой ответ)",
        apply_lesson_id=apply_id,
        apply_lesson_content=apply_content,
        apply_lesson_title_hint=apply_title_hint,
    )


# ── Regenerate module / lesson ──────────────────────────────────────────


async def _regenerate_module_job(
    job_id: str,
    module_id: UUID,
    guidance: str,
    language: str,
    tenant_id: UUID,
    user_id: UUID,
):
    """Background task: re-architect + rewrite a single module + its lessons.
    Keeps the same AIJob record so the frontend can poll /jobs/{id}.
    """
    from app.core.db import async_session_factory
    from app.modules.lessons.models import Module, Lesson
    from app.modules.quizzes.models import Quiz, Question, QuizChoice
    from app.modules.ai.pipeline import run_writer, run_assessment
    from app.modules.ai.ingestion import VectorStore

    async with async_session_factory() as session:
        try:
            await update_ai_job(session, job_id, status="running", stage="architect",
                                progress=10, message="Анализируем модуль…")

            module = await session.get(Module, module_id)
            if not module or module.tenant_id != tenant_id:
                raise ValueError("Module not found")

            course = (
                await session.execute(
                    select(Course).where(Course.id == module.course_id)
                )
            ).scalar_one()
            old_lessons_q = await session.execute(
                select(Lesson).where(Lesson.module_id == module_id).order_by(Lesson.order_index)
            )
            old_lessons = old_lessons_q.scalars().all()

            # Generate new module title + lesson plan with architect-style prompt.
            llm = await ResilientLLMClient.from_settings_async(temperature=0.7, max_tokens=1500)
            plan_prompt = (
                f"Курс: «{course.title}». Текущий модуль: «{module.title}» "
                f"(описание: {module.description or '(пусто)'}). "
                f"В модуле {len(old_lessons)} уроков: "
                + "; ".join(f'«{l.title}»' for l in old_lessons)
                + ".\n\n"
                f"Дополнительные пожелания методолога: {guidance or '(нет)'}\n\n"
                "Сгенерируй JSON со схемой нового модуля в том же формате:\n"
                '{"title": "...", "description": "...", '
                '"lessons": [{"title": "...", "description": "...", '
                '"duration_minutes": 10}, ...]}\n'
                "Сохрани количество уроков и общий объём (±20%). Верни ТОЛЬКО JSON, без markdown."
            )
            plan_resp = await llm.ainvoke(
                [
                    {"role": "system", "content": get_renderer().render("router/system_architect_module_regen.md")},
                    {"role": "user", "content": plan_prompt},
                ]
            )
            plan_text = (plan_resp.content or "").strip()
            # Strip markdown fences if any
            if plan_text.startswith("```"):
                plan_text = plan_text.strip("`")
                if plan_text.startswith("json"):
                    plan_text = plan_text[4:]
                plan_text = plan_text.strip("`\n ")

            import json
            try:
                plan = json.loads(plan_text)
            except Exception:
                logger.warning(f"Module regen — bad JSON, using raw text as title. Got: {plan_text[:200]}")
                plan = {"title": module.title, "description": module.description, "lessons": [
                    {"title": l.title, "description": l.description or "", "duration_minutes": (l.duration_seconds or 600) // 60}
                    for l in old_lessons
                ]}

            # Update module title/description in place.
            module.title = (plan.get("title") or module.title).strip()[:255]
            module.description = (plan.get("description") or module.description).strip()
            new_lessons_plan = plan.get("lessons") or []
            if not isinstance(new_lessons_plan, list) or len(new_lessons_plan) != len(old_lessons):
                # Fallback: keep old titles
                new_lessons_plan = [
                    {"title": l.title, "description": l.description or "",
                     "duration_minutes": (l.duration_seconds or 600) // 60}
                    for l in old_lessons
                ]

            await session.flush()
            await update_ai_job(session, job_id, stage="content_generation",
                                progress=30, message="Переписываем уроки…")

            store = VectorStore()
            # Rewrite each lesson sequentially using existing run_writer contract.
            for old_l, new_plan in zip(old_lessons, new_lessons_plan):
                old_l.title = (new_plan.get("title") or old_l.title).strip()[:255]
                if "duration_minutes" in new_plan:
                    try:
                        old_l.duration_seconds = int(new_plan["duration_minutes"]) * 60
                    except (TypeError, ValueError):
                        pass

                # Reuse writer to generate new content for this lesson.
                course_topic = course.title
                lesson_topic = old_l.title
                # Writer expects str content. We ask for a full rewrite.
                rewrite_prompt = (
                    f"Ты автор учебного контента. Перепиши урок «{lesson_topic}» "
                    f"в рамках курса «{course_topic}» (модуль «{module.title}»).\n"
                    f"Описание: {new_plan.get('description') or '(нет)'}.\n"
                    f"Дополнительно от методолога: {guidance or '(нет)'}.\n\n"
                    f"Длительность: ~{old_l.duration_seconds // 60 if old_l.duration_seconds else 10} минут.\n\n"
                    "Верни ТОЛЬКО текст урока (без заголовка, без markdown-обёрток). "
                    "Структура: краткое введение → основные разделы с подзаголовками → практический пример → резюме."
                )
                content_resp = await llm.ainvoke(
                    [
                        {"role": "system", "content": get_renderer().render("router/system_writer_lesson_regen_module.md")},
                        {"role": "user", "content": rewrite_prompt},
                    ]
                )
                new_content = (content_resp.content or "").strip()
                if new_content:
                    old_l.content = new_content
                    old_l.ai_generated = True

                # Regenerate quiz for this lesson (delete old, create new).
                old_quizzes = (await session.execute(
                    select(Quiz).where(Quiz.lesson_id == old_l.id)
                )).scalars().all()
                for q in old_quizzes:
                    await session.delete(q)
                await session.flush()

                assess_prompt = (
                    f"Сгенерируй 3 тестовых вопроса по уроку:\n\n{(old_l.content or '')[:3000]}\n\n"
                    "Верни JSON: [{\"text\": \"...\", \"choices\": [\"...\",\"...\",\"...\",\"...\"], "
                    "\"correct_index\": 0, \"explanation\": \"...\"}, ...]"
                )
                assess_resp = await llm.ainvoke(
                    [
                        {"role": "system", "content": get_renderer().render("router/system_quiz_regen_module.md")},
                        {"role": "user", "content": assess_prompt},
                    ]
                )
                assess_text = (assess_resp.content or "").strip()
                if assess_text.startswith("```"):
                    assess_text = assess_text.strip("`")
                    if assess_text.startswith("json"):
                        assess_text = assess_text[4:]
                    assess_text = assess_text.strip("`\n ")
                try:
                    questions = json.loads(assess_text)
                except Exception:
                    logger.warning(f"Lesson regen — bad JSON for quiz, skipping. Got: {assess_text[:200]}")
                    questions = []

                if isinstance(questions, list) and questions:
                    new_quiz = Quiz(
                        id=uuid4(), lesson_id=old_l.id, tenant_id=tenant_id,
                        title=f"Тест: {old_l.title}",
                        pass_score=80, attempt_limit=3, deferral_days=7,
                    )
                    session.add(new_quiz)
                    await session.flush()
                    for qi, q in enumerate(questions):
                        if not isinstance(q, dict):
                            continue
                        question = Question(
                            id=uuid4(),
                            quiz_id=new_quiz.id,
                            text=str(q.get("text", ""))[:2000],
                            type="single",
                            points=1,
                            explanation=str(q.get("explanation", ""))[:1000] or None,
                            order_index=qi,
                        )
                        session.add(question)
                        await session.flush()
                        choices = q.get("choices") or []
                        correct_index = int(q.get("correct_index", 0))
                        for ci, choice_text in enumerate(choices):
                            session.add(QuizChoice(
                                id=uuid4(),
                                question_id=question.id,
                                text=str(choice_text)[:500],
                                is_correct=(ci == correct_index),
                                order_index=ci,
                            ))

                await session.flush()

            await update_ai_job(session, job_id, status="completed",
                                progress=100, stage="saving", message="Модуль переписан")
            await session.commit()
        except Exception as e:
            logger.error(f"Module regeneration failed: {e}", exc_info=True)
            try:
                await update_ai_job(session, job_id, status="failed",
                                    progress=0, stage="failed",
                                    message=f"Ошибка: {str(e)[:300]}")
                await session.commit()
            except Exception:
                pass
        finally:
            _running_tasks.pop(job_id, None)


async def _regenerate_lesson_job(
    job_id: str,
    lesson_id: UUID,
    guidance: str,
    regenerate_quiz: bool,
    tenant_id: UUID,
    user_id: UUID,
):
    from app.core.db import async_session_factory
    from app.modules.lessons.models import Module, Lesson
    from app.modules.quizzes.models import Quiz, Question, QuizChoice
    import json as _json

    async with async_session_factory() as session:
        try:
            await update_ai_job(session, job_id, status="running", stage="content_generation",
                                progress=20, message="Переписываем урок…")

            lesson = await session.get(Lesson, lesson_id)
            if not lesson or lesson.tenant_id != tenant_id:
                raise ValueError("Lesson not found")
            module = await session.get(Module, lesson.module_id)
            course = (await session.execute(
                select(Course).where(Course.id == module.course_id)
            )).scalar_one()

            llm = await ResilientLLMClient.from_settings_async(temperature=0.7, max_tokens=2000)
            rewrite_prompt = (
                f"Ты автор LMS-уроков. Перепиши урок «{lesson.title}» "
                f"в рамках курса «{course.title}» (модуль «{module.title}»).\n"
                f"Длительность: ~{lesson.duration_seconds // 60 if lesson.duration_seconds else 10} минут.\n"
                f"Дополнительно от методолога: {guidance or '(нет)'}.\n\n"
                "Верни ТОЛЬКО текст урока (без заголовка, без markdown-обёрток). "
                "Структура: краткое введение → основные разделы с подзаголовками → практический пример → резюме."
            )
            resp = await llm.ainvoke(
                [
                    {"role": "system", "content": get_renderer().render("router/system_writer_lesson_regen.md")},
                    {"role": "user", "content": rewrite_prompt},
                ]
            )
            new_content = (resp.content or "").strip()
            if new_content:
                lesson.content = new_content
                lesson.ai_generated = True

            await update_ai_job(session, job_id, progress=60,
                                stage="assessment", message="Обновляем тест…")
            await session.flush()

            if regenerate_quiz:
                # delete old quizzes (cascade clears questions/choices)
                old_qs = (await session.execute(
                    select(Quiz).where(Quiz.lesson_id == lesson.id)
                )).scalars().all()
                for q in old_qs:
                    await session.delete(q)
                await session.flush()

                assess_prompt = (
                    f"Сгенерируй 3 тестовых вопроса по уроку:\n\n{(lesson.content or '')[:3000]}\n\n"
                    "Верни JSON: [{\"text\": \"...\", \"choices\": [\"...\",\"...\",\"...\",\"...\"], "
                    "\"correct_index\": 0, \"explanation\": \"...\"}, ...]"
                )
                assess_resp = await llm.ainvoke(
                    [
                        {"role": "system", "content": get_renderer().render("router/system_quiz_regen_module.md")},
                        {"role": "user", "content": assess_prompt},
                    ]
                )
                assess_text = (assess_resp.content or "").strip()
                if assess_text.startswith("```"):
                    assess_text = assess_text.strip("`")
                    if assess_text.startswith("json"):
                        assess_text = assess_text[4:]
                    assess_text = assess_text.strip("`\n ")
                try:
                    questions = _json.loads(assess_text)
                except Exception:
                    logger.warning(f"Lesson regen — bad JSON for quiz, skipping")
                    questions = []

                if isinstance(questions, list) and questions:
                    new_quiz = Quiz(
                        id=uuid4(), lesson_id=lesson.id, tenant_id=tenant_id,
                        title=f"Тест: {lesson.title}",
                        pass_score=80, attempt_limit=3, deferral_days=7,
                    )
                    session.add(new_quiz)
                    await session.flush()
                    for qi, q in enumerate(questions):
                        if not isinstance(q, dict):
                            continue
                        question = Question(
                            id=uuid4(),
                            quiz_id=new_quiz.id,
                            text=str(q.get("text", ""))[:2000],
                            type="single",
                            points=1,
                            explanation=str(q.get("explanation", ""))[:1000] or None,
                            order_index=qi,
                        )
                        session.add(question)
                        await session.flush()
                        choices = q.get("choices") or []
                        correct_index = int(q.get("correct_index", 0))
                        for ci, choice_text in enumerate(choices):
                            session.add(QuizChoice(
                                id=uuid4(),
                                question_id=question.id,
                                text=str(choice_text)[:500],
                                is_correct=(ci == correct_index),
                                order_index=ci,
                            ))

            await update_ai_job(session, job_id, status="completed",
                                progress=100, stage="saving", message="Урок переписан")
            await session.commit()
        except Exception as e:
            logger.error(f"Lesson regeneration failed: {e}", exc_info=True)
            try:
                await update_ai_job(session, job_id, status="failed",
                                    progress=0, stage="failed",
                                    message=f"Ошибка: {str(e)[:300]}")
                await session.commit()
            except Exception:
                pass
        finally:
            _running_tasks.pop(job_id, None)


@router.post("/regenerate-module/{module_id}", response_model=AIJobResponse, status_code=202)
async def regenerate_module(
    module_id: UUID,
    req: AIRegenerateModuleRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("superadmin", "admin", "org_admin", "teacher")),
):
    """Rewrite a module and all its lessons (and their quizzes).

    Returns AIJobResponse — poll /ai/jobs/{id} for progress, same as
    initial generation. Cancelling via /ai/jobs/{id}/cancel works.
    """
    from app.modules.lessons.models import Module

    module = await db.get(Module, module_id)
    if not module or module.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="Module not found")

    job = await create_ai_job(
        db=db, tenant_id=user.tenant_id, user_id=user.id, course_id=module.course_id,
        params={"action": "regenerate_module", "module_id": str(module_id),
                "guidance": req.guidance, "language": req.language},
    )
    await db.commit()

    task = asyncio.create_task(
        _regenerate_module_job(
            job_id=job.id,
            module_id=module_id,
            guidance=req.guidance,
            language=req.language,
            tenant_id=user.tenant_id,
            user_id=user.id,
        )
    )
    _running_tasks[job.id] = task

    return AIJobResponse(
        id=job.id, status="pending", course_id=module.course_id,
        created_at=job.created_at, progress=0, stage="queued",
        message="Перегенерация модуля запущена",
    )


@router.post("/regenerate-lesson/{lesson_id}", response_model=AIJobResponse, status_code=202)
async def regenerate_lesson(
    lesson_id: UUID,
    req: AIRegenerateLessonRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("superadmin", "admin", "org_admin", "teacher")),
):
    """Rewrite a single lesson (and optionally its quiz)."""
    from app.modules.lessons.models import Module, Lesson

    lesson = await db.get(Lesson, lesson_id)
    if not lesson or lesson.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="Lesson not found")
    module = await db.get(Module, lesson.module_id)

    job = await create_ai_job(
        db=db, tenant_id=user.tenant_id, user_id=user.id, course_id=module.course_id,
        params={"action": "regenerate_lesson", "lesson_id": str(lesson_id),
                "guidance": req.guidance, "regenerate_quiz": req.regenerate_quiz},
    )
    await db.commit()

    task = asyncio.create_task(
        _regenerate_lesson_job(
            job_id=job.id,
            lesson_id=lesson_id,
            guidance=req.guidance,
            regenerate_quiz=req.regenerate_quiz,
            tenant_id=user.tenant_id,
            user_id=user.id,
        )
    )
    _running_tasks[job.id] = task

    return AIJobResponse(
        id=job.id, status="pending", course_id=module.course_id,
        created_at=job.created_at, progress=0, stage="queued",
        message="Перегенерация урока запущена",
    )
