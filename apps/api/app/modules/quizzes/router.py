"""Quiz API router"""
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

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
)
from app.modules.quizzes.service import (
    get_quiz_with_questions,
    grade_quiz,
    get_user_attempts,
    get_quiz_stats,
)

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
        out.append(await get_quiz_with_questions(db, q.id, user.tenant_id))
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
