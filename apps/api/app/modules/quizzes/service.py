"""Quiz service — grading and attempt management"""
from typing import Iterable
from uuid import UUID
from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.modules.quizzes.models import Quiz, Question, QuizChoice, QuizAttempt


async def get_quiz_with_questions(db: AsyncSession, quiz_id: UUID, tenant_id: UUID):
    """Get quiz with all questions and choices (single quiz).

    Convenience wrapper around get_quizzes_with_questions for the common
    single-quiz case. Returns the first item from the batched call, or
    None if no quiz matches.
    """
    results = await get_quizzes_with_questions(db, [quiz_id], tenant_id)
    return results[0] if results else None


async def get_quizzes_with_questions(
    db: AsyncSession, quiz_ids: Iterable[UUID], tenant_id: UUID
) -> list[dict]:
    """Fetch many quizzes (with their questions+choices) in 3 batched queries.

    Replaces the per-quiz N+1 pattern of calling get_quiz_with_questions()
    in a loop. Three queries total, regardless of quiz count:
      1. SELECT quizzes WHERE id IN (...) AND tenant_id = ?
      2. SELECT questions WHERE quiz_id IN (...) ORDER BY order_index
      3. SELECT quiz_choices WHERE question_id IN (...) ORDER BY order_index

    Returns a list of quiz dicts in the same shape as
    get_quiz_with_questions(), in the order the quizzes came back from
    the first query. Empty input → empty list.
    """
    quiz_ids = list(quiz_ids)
    if not quiz_ids:
        return []

    # Query 1 — quizzes, scoped to tenant.
    quizzes_result = await db.execute(
        select(Quiz).where(
            Quiz.id.in_(quiz_ids),
            Quiz.tenant_id == tenant_id,
        )
    )
    quizzes = quizzes_result.scalars().all()
    if not quizzes:
        return []

    valid_quiz_ids = [q.id for q in quizzes]

    # Query 2 — all questions across these quizzes, ordered.
    questions_result = await db.execute(
        select(Question)
        .where(
            Question.quiz_id.in_(valid_quiz_ids),
            Question.tenant_id == tenant_id,
        )
        .order_by(Question.quiz_id, Question.order_index)
    )
    questions = questions_result.scalars().all()

    # Query 3 — all choices for those questions, ordered.
    question_ids = [q.id for q in questions]
    choices_by_qid: dict[UUID, list[QuizChoice]] = {qid: [] for qid in question_ids}
    if question_ids:
        choices_result = await db.execute(
            select(QuizChoice)
            .where(QuizChoice.question_id.in_(question_ids))
            .order_by(QuizChoice.question_id, QuizChoice.order_index)
        )
        for c in choices_result.scalars().all():
            choices_by_qid.setdefault(c.question_id, []).append(c)

    # Assemble in Python — one pass over quizzes, one over questions.
    questions_by_quiz: dict[UUID, list[Question]] = {qid: [] for qid in valid_quiz_ids}
    for q in questions:
        questions_by_quiz.setdefault(q.quiz_id, []).append(q)

    out: list[dict] = []
    for quiz in quizzes:
        out.append({
            "id": quiz.id,
            "lesson_id": quiz.lesson_id,
            "title": quiz.title,
            "pass_score": quiz.pass_score,
            "time_limit": quiz.time_limit,
            "attempt_limit": quiz.attempt_limit,
            "deferral_days": quiz.deferral_days,
            "questions": [
                {
                    "id": q.id,
                    "text": q.text,
                    "type": q.type,
                    "points": q.points,
                    "explanation": q.explanation,
                    "order_index": q.order_index,
                    "choices": [
                        {
                            "id": c.id,
                            "text": c.text,
                            "order_index": c.order_index,
                            "is_correct": c.is_correct,
                        }
                        for c in choices_by_qid.get(q.id, [])
                    ],
                }
                for q in questions_by_quiz.get(quiz.id, [])
            ],
        })
    return out


async def _is_quiz_expired(
    db: AsyncSession, quiz: Quiz, user_id: UUID, tenant_id: UUID
) -> bool:
    """Return True if deferral window expired (no lesson completion in time).

    If user never completed the lesson, deferral hasn't started — quiz is NOT
    considered expired (methodologist may have shared quiz without forced progression).
    """
    from app.models.progress import Progress
    progress_result = await db.execute(
        select(Progress).where(
            Progress.user_id == user_id,
            Progress.lesson_id == quiz.lesson_id,
            Progress.tenant_id == tenant_id,
        )
    )
    progress = progress_result.scalar_one_or_none()
    if not progress or not progress.completed_at:
        return False
    deadline = progress.completed_at + timedelta(days=quiz.deferral_days)
    return datetime.now(timezone.utc) > deadline


async def grade_quiz(
    db: AsyncSession,
    quiz_id: UUID,
    user_id: UUID,
    tenant_id: UUID,
    answers: list[dict],
    time_spent_seconds: int | None = None,
) -> dict:
    """Grade a quiz submission and return results."""
    quiz = await db.get(Quiz, quiz_id)
    if not quiz:
        raise ValueError("Quiz not found")

    # Enforce deferral window
    if await _is_quiz_expired(db, quiz, user_id, tenant_id):
        raise ValueError(
            f"Quiz deferral window expired ({quiz.deferral_days} days). "
            "Contact your methodologist to re-open."
        )

    # Check attempt limit
    attempt_count_result = await db.execute(
        select(func.count(QuizAttempt.id)).where(
            QuizAttempt.quiz_id == quiz_id,
            QuizAttempt.user_id == user_id,
            QuizAttempt.tenant_id == tenant_id,
        )
    )
    attempt_count = attempt_count_result.scalar() or 0
    if attempt_count >= quiz.attempt_limit:
        raise ValueError(f"Attempt limit reached ({quiz.attempt_limit})")

    # Grade each answer
    total_points = 0
    earned_points = 0
    graded_answers = []

    for answer in answers:
        question_id = answer.get("question_id")
        selected_ids = answer.get("selected_choice_ids", [])

        question = await db.get(Question, question_id)
        if not question:
            continue

        total_points += question.points

        # Get correct choices
        correct_result = await db.execute(
            select(QuizChoice.id).where(
                QuizChoice.question_id == question_id,
                QuizChoice.is_correct == True,
            )
        )
        correct_ids = set(correct_result.scalars().all())

        # Get selected choices
        selected_set = set(UUID(str(sid)) for sid in selected_ids)

        # Check if correct
        is_correct = correct_ids == selected_set
        if is_correct:
            earned_points += question.points

        graded_answers.append({
            "question_id": str(question_id),
            "selected_choice_ids": [str(sid) for sid in selected_ids],
            "correct_choice_ids": [str(cid) for cid in correct_ids],
            "is_correct": is_correct,
            "points_earned": question.points if is_correct else 0,
            "points_possible": question.points,
        })

    # Calculate score
    score_percent = round((earned_points / total_points * 100) if total_points > 0 else 0)
    passed = score_percent >= quiz.pass_score

    # Create attempt
    attempt = QuizAttempt(
        quiz_id=quiz_id,
        user_id=user_id,
        tenant_id=tenant_id,
        score_percent=score_percent,
        total_points=total_points,
        earned_points=earned_points,
        passed=passed,
        answers=graded_answers,
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
        time_spent_seconds=time_spent_seconds,
    )
    db.add(attempt)
    await db.flush()
    await db.refresh(attempt)

    correct_count = sum(1 for a in graded_answers if a["is_correct"])

    return {
        "attempt": attempt,
        "correct_answers": correct_count,
        "total_questions": len(graded_answers),
        "passed": passed,
        "message": f"{'Поздравляем! Вы прошли тест.' if passed else 'Тест не пройден. Попробуйте ещё раз.'}",
    }


async def get_user_attempts(
    db: AsyncSession, quiz_id: UUID, user_id: UUID, tenant_id: UUID
) -> list[QuizAttempt]:
    """Get all attempts by a user for a quiz (with tenant isolation)."""
    result = await db.execute(
        select(QuizAttempt)
        .where(
            QuizAttempt.quiz_id == quiz_id,
            QuizAttempt.user_id == user_id,
            QuizAttempt.tenant_id == tenant_id,
        )
        .order_by(QuizAttempt.started_at.desc())
    )
    return result.scalars().all()


async def get_quiz_stats(db: AsyncSession, quiz_id: UUID, tenant_id: UUID) -> dict:
    """Get quiz statistics (with tenant isolation)."""
    total_result = await db.execute(
        select(func.count(QuizAttempt.id)).where(
            QuizAttempt.quiz_id == quiz_id,
            QuizAttempt.tenant_id == tenant_id,
        )
    )
    total_attempts = total_result.scalar() or 0

    passed_result = await db.execute(
        select(func.count(QuizAttempt.id)).where(
            QuizAttempt.quiz_id == quiz_id,
            QuizAttempt.passed == True,
            QuizAttempt.tenant_id == tenant_id,
        )
    )
    passed_count = passed_result.scalar() or 0

    avg_result = await db.execute(
        select(func.avg(QuizAttempt.score_percent)).where(
            QuizAttempt.quiz_id == quiz_id,
            QuizAttempt.tenant_id == tenant_id,
        )
    )
    avg_score = round(avg_result.scalar() or 0, 1)

    return {
        "total_attempts": total_attempts,
        "passed_count": passed_count,
        "pass_rate": round((passed_count / total_attempts * 100) if total_attempts > 0 else 0, 1),
        "average_score": avg_score,
    }
