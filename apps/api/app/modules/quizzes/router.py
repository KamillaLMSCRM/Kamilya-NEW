"""Quiz API router"""
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.db import get_db
from app.modules.quizzes.schemas import (
    QuizResponse,
    QuizSubmission,
    QuizAttemptResponse,
    QuizResultResponse,
)
from app.modules.quizzes.service import (
    get_quiz_with_questions,
    grade_quiz,
    get_user_attempts,
    get_quiz_stats,
)

router = APIRouter(prefix="/quizzes", tags=["quizzes"])


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
    return await get_user_attempts(db, quiz_id, user.id)


@router.get("/{quiz_id}/stats")
async def quiz_stats(
    quiz_id: UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Get quiz statistics (admin view)."""
    return await get_quiz_stats(db, quiz_id)
