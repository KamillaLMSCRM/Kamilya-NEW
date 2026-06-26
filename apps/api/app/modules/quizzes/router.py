"""Quiz API router"""
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.auth import get_current_user, require_role
from app.core.db import get_db
from app.modules.quizzes.models import Quiz, Question, QuizChoice
from app.models.users import User
from app.modules.quizzes.schemas import (
    QuizResponse,
    QuizSubmission,
    QuizAttemptResponse,
    QuizResultResponse,
    QuizCreate,
    QuizUpdate,
    QuestionCreate,
    QuestionUpdate,
    QuizChoiceCreate,
    QuizChoiceUpdate,
    QuizGenerateRequest,
    QuizGenerateResponse,
)
from app.modules.quizzes.service import (
    get_quiz_with_questions,
    grade_quiz,
    get_user_attempts,
    get_quiz_stats,
)
from app.modules.quizzes.ai import generate_quiz_draft

router = APIRouter(prefix="/quizzes", tags=["quizzes"])


@router.get("", response_model=list[QuizResponse])
async def list_quizzes(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List all quizzes for the current tenant."""
    result = await db.execute(
        select(Quiz).where(Quiz.tenant_id == user.tenant_id).order_by(Quiz.created_at.desc())
    )
    quizzes = result.scalars().all()
    out = []
    for q in quizzes:
        quiz_data = await get_quiz_with_questions(db, q.id, user.tenant_id)
        if quiz_data:
            out.append(quiz_data)
    return out


@router.get("/enrolled")
async def list_enrolled_quizzes(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List quizzes from courses the user is enrolled in, with attempt status."""
    from app.modules.enrollments.models import Enrollment
    from app.modules.lessons.models import Module, Lesson
    from app.modules.quizzes.models import QuizAttempt

    enrollments = await db.execute(
        select(Enrollment.course_id).where(
            Enrollment.user_id == user.id,
            Enrollment.tenant_id == user.tenant_id,
        )
    )
    course_ids = [r[0] for r in enrollments.fetchall()]
    if not course_ids:
        return []

    lessons_q = await db.execute(
        select(Lesson.id, Lesson.title, Module.title.label("module_title"), Module.course_id)
        .join(Module, Lesson.module_id == Module.id)
        .where(Module.course_id.in_(course_ids))
    )
    lesson_rows = lessons_q.fetchall()
    lesson_ids = [r[0] for r in lesson_rows]
    lesson_map = {r[0]: {"title": r[1], "module_title": r[2], "course_id": str(r[3])} for r in lesson_rows}

    if not lesson_ids:
        return []

    quizzes_q = await db.execute(
        select(Quiz).where(Quiz.lesson_id.in_(lesson_ids), Quiz.tenant_id == user.tenant_id)
    )
    quizzes = {str(q.lesson_id): q for q in quizzes_q.scalars().all()}
    if not quizzes:
        return []

    attempts_q = await db.execute(
        select(
            QuizAttempt.quiz_id,
            QuizAttempt.score_percent,
            QuizAttempt.passed,
            QuizAttempt.completed_at,
            func.count(QuizAttempt.id).label("attempts_count"),
        )
        .where(
            QuizAttempt.user_id == user.id,
            QuizAttempt.tenant_id == user.tenant_id,
            QuizAttempt.quiz_id.in_([q.id for q in quizzes.values()]),
        )
        .group_by(QuizAttempt.quiz_id, QuizAttempt.score_percent, QuizAttempt.passed, QuizAttempt.completed_at)
        .order_by(QuizAttempt.completed_at.desc())
    )
    attempts = attempts_q.fetchall()
    attempt_map = {}
    for a in attempts:
        qid = str(a[0])
        if qid not in attempt_map:
            attempt_map[qid] = {
                "score_percent": a[1],
                "passed": a[2],
                "completed_at": a[3].isoformat() if a[3] else None,
                "attempts_count": a[4],
            }
        elif a[2] and not attempt_map[qid]["passed"]:
            attempt_map[qid] = {
                "score_percent": a[1],
                "passed": a[2],
                "completed_at": a[3].isoformat() if a[3] else None,
                "attempts_count": a[4],
            }
        else:
            attempt_map[qid]["attempts_count"] = (attempt_map[qid].get("attempts_count") or 0) + a[4]

    out = []
    from app.models.progress import Progress
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    for lid, quiz in quizzes.items():
        li = lesson_map.get(lid, {})
        att = attempt_map.get(str(quiz.id))

        # Compute is_expired from progress.completed_at + deferral_days
        is_expired = False
        prog_result = await db.execute(
            select(Progress.completed_at).where(
                Progress.user_id == user.id,
                Progress.lesson_id == quiz.lesson_id,
                Progress.tenant_id == user.tenant_id,
            )
        )
        prog_completed_at = prog_result.scalar_one_or_none()
        if prog_completed_at and quiz.deferral_days > 0:
            is_expired = now > prog_completed_at + timedelta(days=quiz.deferral_days)

        out.append({
            "quiz_id": str(quiz.id),
            "quiz_title": quiz.title,
            "lesson_title": li.get("title", ""),
            "module_title": li.get("module_title", ""),
            "course_id": li.get("course_id", ""),
            "pass_score": quiz.pass_score,
            "deferral_days": quiz.deferral_days,
            "attempt_limit": quiz.attempt_limit,
            "score_percent": att["score_percent"] if att else None,
            "passed": att["passed"] if att else False,
            "completed_at": att["completed_at"] if att else None,
            "attempts_count": att["attempts_count"] if att else 0,
            "is_expired": is_expired,
        })

    out.sort(key=lambda x: (x["passed"], x.get("completed_at") or ""))
    return out


@router.get("/by-lesson/{lesson_id}", response_model=QuizResponse)
async def get_quiz_by_lesson(
    lesson_id: UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Get quiz for a given lesson (only returns first quiz if multiple exist)."""
    result = await db.execute(
        select(Quiz).where(Quiz.lesson_id == lesson_id, Quiz.tenant_id == user.tenant_id).limit(1)
    )
    quiz = result.scalar_one_or_none()
    if not quiz:
        raise HTTPException(status_code=404, detail="No quiz for this lesson")
    return await get_quiz_with_questions(db, quiz.id, user.tenant_id)


@router.get("/{quiz_id}", response_model=QuizResponse)
async def get_quiz(
    quiz_id: UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Get quiz with questions (without correct answers)."""
    quiz = await get_quiz_with_questions(db, quiz_id, user.tenant_id)
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")
    return quiz


@router.post("/{quiz_id}/submit", response_model=QuizResultResponse)
async def submit_quiz(
    quiz_id: UUID,
    req: QuizSubmission,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Submit quiz answers and get graded results."""
    try:
        answers_dicts = [a.model_dump() for a in req.answers]
        result = await grade_quiz(
            db=db,
            quiz_id=quiz_id,
            user_id=user.id,
            tenant_id=user.tenant_id,
            answers=answers_dicts,
            time_spent_seconds=req.time_spent_seconds,
        )
        # Update quiz assignment status if exists
        try:
            from app.modules.quizzes.assignment_service import update_assignment_status
            await update_assignment_status(
                db, quiz_id, user.id, user.tenant_id,
                result["attempt"]["score_percent"],
                result["passed"],
            )
        except Exception:
            pass
        return QuizResultResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{quiz_id}/attempts", response_model=list[QuizAttemptResponse])
async def list_attempts(
    quiz_id: UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Get user's attempts for a quiz."""
    return await get_user_attempts(db, quiz_id, user.id, user.tenant_id)


@router.get("/{quiz_id}/stats")
async def quiz_stats(
    quiz_id: UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Get quiz statistics (admin view)."""
    return await get_quiz_stats(db, quiz_id, user.tenant_id)


# ── CRUD: Quiz ──────────────────────────────────────────────


@router.post("", response_model=QuizResponse, status_code=201)
async def create_quiz(
    req: QuizCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("superadmin", "admin", "org_admin", "teacher")),
):
    """Create a new quiz."""
    from uuid import uuid4
    quiz = Quiz(
        id=uuid4(),
        lesson_id=req.lesson_id,
        tenant_id=user.tenant_id,
        title=req.title,
        pass_score=req.pass_score,
        time_limit=req.time_limit,
        attempt_limit=req.attempt_limit,
    )
    db.add(quiz)
    await db.flush()
    await db.refresh(quiz)
    return await get_quiz_with_questions(db, quiz.id, user.tenant_id)


@router.post("/generate", response_model=QuizGenerateResponse)
async def generate_quiz(
    req: QuizGenerateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("superadmin", "admin", "org_admin", "teacher")),
):
    """AI-generate a draft quiz from a lesson's content.

    Sync endpoint — the LLM answers in ~10s on Qwen self-hosted and
    ~5s on the DeepSeek fallback. We deliberately do NOT write to the
    DB; the methodologist reviews the draft in the UI and saves it with
    a follow-up POST /v1/quizzes in one click. This keeps the AI from
    silently publishing bad questions to employees.

    Tenant isolation: the lesson must belong to the caller's tenant,
    otherwise 404 (never 403 — see AGENTS.md).
    """
    from app.modules.lessons.models import Lesson

    lesson = await db.get(Lesson, req.lesson_id)
    if not lesson or lesson.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="Lesson not found")

    title = (lesson.title or "").strip() or "Урок без названия"
    content = (lesson.content or "").strip()

    try:
        draft = await generate_quiz_draft(
            lesson_title=title,
            lesson_content=content,
            num_questions=req.num_questions,
            difficulty=req.difficulty,
            language=req.language,
            guidance=req.guidance,
        )
    except RuntimeError as e:
        # 502 = upstream (LLM) error. Don't leak internals — the message
        # we set in ai.py is already user-safe.
        raise HTTPException(status_code=502, detail=str(e))

    if not draft["questions"]:
        raise HTTPException(
            status_code=502,
            detail="AI вернул пустой или нечитаемый ответ. Попробуйте ещё раз или упростите запрос.",
        )

    return QuizGenerateResponse(
        lesson_id=lesson.id,
        suggested_title=draft["suggested_title"],
        suggested_pass_score=draft["suggested_pass_score"],
        questions=draft["questions"],
        model_used=draft.get("model_used"),
        latency_ms=draft.get("latency_ms"),
    )


@router.put("/{quiz_id}", response_model=QuizResponse)
async def update_quiz(
    quiz_id: UUID,
    req: QuizUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("superadmin", "admin", "org_admin", "teacher")),
):
    """Update quiz settings."""
    quiz = await db.get(Quiz, quiz_id)
    if not quiz or quiz.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="Quiz not found")
    if req.title is not None:
        quiz.title = req.title
    if req.pass_score is not None:
        quiz.pass_score = req.pass_score
    if req.time_limit is not None:
        quiz.time_limit = req.time_limit
    if req.attempt_limit is not None:
        quiz.attempt_limit = req.attempt_limit
    await db.flush()
    return await get_quiz_with_questions(db, quiz.id, user.tenant_id)


@router.delete("/{quiz_id}", status_code=204)
async def delete_quiz(
    quiz_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("superadmin", "admin", "org_admin", "teacher")),
):
    """Delete a quiz and all its questions/choices."""
    quiz = await db.get(Quiz, quiz_id)
    if not quiz or quiz.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="Quiz not found")
    # Delete questions and choices first (cascade should handle, but be explicit)
    questions = await db.execute(select(Question).where(Question.quiz_id == quiz_id))
    for q in questions.scalars().all():
        choices = await db.execute(select(QuizChoice).where(QuizChoice.question_id == q.id))
        for c in choices.scalars().all():
            await db.delete(c)
        await db.delete(q)
    await db.delete(quiz)


# ── CRUD: Questions ─────────────────────────────────────────


@router.post("/{quiz_id}/questions", response_model=QuizResponse, status_code=201)
async def create_question(
    quiz_id: UUID,
    req: QuestionCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("superadmin", "admin", "org_admin", "teacher")),
):
    """Add a question to a quiz with optional choices."""
    from uuid import uuid4
    quiz = await db.get(Quiz, quiz_id)
    if not quiz or quiz.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="Quiz not found")
    question = Question(
        id=uuid4(),
        quiz_id=quiz_id,
        text=req.text,
        type=req.type,
        points=req.points,
        explanation=req.explanation,
        order_index=req.order_index,
        pool_group=req.pool_group,
    )
    db.add(question)
    await db.flush()
    for ci, choice_req in enumerate(req.choices):
        choice = QuizChoice(
            id=uuid4(),
            question_id=question.id,
            text=choice_req.text,
            is_correct=choice_req.is_correct,
            order_index=choice_req.order_index if choice_req.order_index else ci,
        )
        db.add(choice)
    await db.flush()
    return await get_quiz_with_questions(db, quiz_id, user.tenant_id)


@router.put("/{quiz_id}/questions/{question_id}", response_model=QuizResponse)
async def update_question(
    quiz_id: UUID,
    question_id: UUID,
    req: QuestionUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("superadmin", "admin", "org_admin", "teacher")),
):
    """Update a question's properties."""
    quiz = await db.get(Quiz, quiz_id)
    if not quiz or quiz.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="Quiz not found")
    question = await db.get(Question, question_id)
    if not question or question.quiz_id != quiz_id:
        raise HTTPException(status_code=404, detail="Question not found")
    if req.text is not None:
        question.text = req.text
    if req.type is not None:
        question.type = req.type
    if req.points is not None:
        question.points = req.points
    if req.explanation is not None:
        question.explanation = req.explanation
    if req.order_index is not None:
        question.order_index = req.order_index
    await db.flush()
    return await get_quiz_with_questions(db, quiz_id, user.tenant_id)


@router.delete("/{quiz_id}/questions/{question_id}", response_model=QuizResponse)
async def delete_question(
    quiz_id: UUID,
    question_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("superadmin", "admin", "org_admin", "teacher")),
):
    """Delete a question and its choices."""
    quiz = await db.get(Quiz, quiz_id)
    if not quiz or quiz.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="Quiz not found")
    question = await db.get(Question, question_id)
    if not question or question.quiz_id != quiz_id:
        raise HTTPException(status_code=404, detail="Question not found")
    choices = await db.execute(select(QuizChoice).where(QuizChoice.question_id == question_id))
    for c in choices.scalars().all():
        await db.delete(c)
    await db.delete(question)
    await db.flush()
    return await get_quiz_with_questions(db, quiz_id, user.tenant_id)


# ── CRUD: Choices ───────────────────────────────────────────


@router.post("/{quiz_id}/questions/{question_id}/choices", response_model=QuizResponse, status_code=201)
async def create_choice(
    quiz_id: UUID,
    question_id: UUID,
    req: QuizChoiceCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("superadmin", "admin", "org_admin", "teacher")),
):
    """Add a choice to a question."""
    from uuid import uuid4
    quiz = await db.get(Quiz, quiz_id)
    if not quiz or quiz.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="Quiz not found")
    question = await db.get(Question, question_id)
    if not question or question.quiz_id != quiz_id:
        raise HTTPException(status_code=404, detail="Question not found")
    choice = QuizChoice(
        id=uuid4(),
        question_id=question_id,
        text=req.text,
        is_correct=req.is_correct,
        order_index=req.order_index,
    )
    db.add(choice)
    await db.flush()
    return await get_quiz_with_questions(db, quiz_id, user.tenant_id)


@router.put("/{quiz_id}/questions/{question_id}/choices/{choice_id}", response_model=QuizResponse)
async def update_choice(
    quiz_id: UUID,
    question_id: UUID,
    choice_id: UUID,
    req: QuizChoiceUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("superadmin", "admin", "org_admin", "teacher")),
):
    """Update a choice."""
    quiz = await db.get(Quiz, quiz_id)
    if not quiz or quiz.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="Quiz not found")
    question = await db.get(Question, question_id)
    if not question or question.quiz_id != quiz_id:
        raise HTTPException(status_code=404, detail="Question not found")
    choice = await db.get(QuizChoice, choice_id)
    if not choice or choice.question_id != question_id:
        raise HTTPException(status_code=404, detail="Choice not found")
    if req.text is not None:
        choice.text = req.text
    if req.is_correct is not None:
        choice.is_correct = req.is_correct
    if req.order_index is not None:
        choice.order_index = req.order_index
    await db.flush()
    return await get_quiz_with_questions(db, quiz_id, user.tenant_id)


@router.delete("/{quiz_id}/questions/{question_id}/choices/{choice_id}", response_model=QuizResponse)
async def delete_choice(
    quiz_id: UUID,
    question_id: UUID,
    choice_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("superadmin", "admin", "org_admin", "teacher")),
):
    """Delete a choice."""
    quiz = await db.get(Quiz, quiz_id)
    if not quiz or quiz.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="Quiz not found")
    question = await db.get(Question, question_id)
    if not question or question.quiz_id != quiz_id:
        raise HTTPException(status_code=404, detail="Question not found")
    choice = await db.get(QuizChoice, choice_id)
    if not choice or choice.question_id != question_id:
        raise HTTPException(status_code=404, detail="Choice not found")
    await db.delete(choice)
    await db.flush()
    return await get_quiz_with_questions(db, quiz_id, user.tenant_id)
