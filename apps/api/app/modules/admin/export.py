"""Export service — CSV/Excel generation"""
import csv
import io
from uuid import UUID
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.users import User
from app.models.courses import Course
from app.models.enrollment import Enrollment
from app.modules.quizzes.models import QuizAttempt


async def export_users_csv(db: AsyncSession, tenant_id: UUID) -> str:
    """Export users to CSV."""
    result = await db.execute(
        select(User).where(User.tenant_id == tenant_id).order_by(User.created_at.desc())
    )
    users = result.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "ID", "Email", "Имя", "Фамилия", "Роль", "Активен",
        "Telegram ID", "Последний вход", "Дата создания"
    ])

    for user in users:
        writer.writerow([
            str(user.id),
            user.email,
            user.first_name,
            user.last_name,
            user.role,
            "Да" if user.is_active else "Нет",
            user.telegram_id or "",
            user.last_login.isoformat() if user.last_login else "",
            user.created_at.isoformat() if user.created_at else "",
        ])

    return output.getvalue()


async def export_courses_csv(db: AsyncSession, tenant_id: UUID) -> str:
    """Export courses to CSV."""
    result = await db.execute(
        select(Course).where(Course.tenant_id == tenant_id).order_by(Course.created_at.desc())
    )
    courses = result.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "ID", "Название", "Описание", "Статус", "AI-сгенерирован",
        "Дата создания", "Дата публикации"
    ])

    for course in courses:
        writer.writerow([
            str(course.id),
            course.title,
            course.description or "",
            course.status,
            "Да" if course.ai_generated else "Нет",
            course.created_at.isoformat() if course.created_at else "",
            course.published_at.isoformat() if course.published_at else "",
        ])

    return output.getvalue()


async def export_enrollments_csv(db: AsyncSession, tenant_id: UUID) -> str:
    """Export enrollments to CSV."""
    result = await db.execute(
        select(Enrollment, Course, User)
        .join(Course, Enrollment.course_id == Course.id)
        .join(User, Enrollment.user_id == User.id)
        .where(Enrollment.tenant_id == tenant_id)
        .order_by(Enrollment.enrolled_at.desc())
    )
    enrollments = result.all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Пользователь", "Email", "Курс", "Статус",
        "Дата записи", "Дата завершения"
    ])

    for enrollment, course, user in enrollments:
        writer.writerow([
            f"{user.first_name} {user.last_name}",
            user.email,
            course.title,
            enrollment.status,
            enrollment.enrolled_at.isoformat() if enrollment.enrolled_at else "",
            enrollment.completed_at.isoformat() if enrollment.completed_at else "",
        ])

    return output.getvalue()


async def export_quiz_results_csv(db: AsyncSession, tenant_id: UUID) -> str:
    """Export quiz results to CSV."""
    result = await db.execute(
        select(QuizAttempt, User)
        .join(User, QuizAttempt.user_id == User.id)
        .where(QuizAttempt.tenant_id == tenant_id)
        .order_by(QuizAttempt.completed_at.desc())
    )
    attempts = result.all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Пользователь", "Email", "Quiz ID", "Оценка (%)",
        "Баллы", "Пройден", "Время (сек)", "Дата"
    ])

    for attempt, user in attempts:
        writer.writerow([
            f"{user.first_name} {user.last_name}",
            user.email,
            str(attempt.quiz_id),
            attempt.score_percent,
            f"{attempt.earned_points}/{attempt.total_points}",
            "Да" if attempt.passed else "Нет",
            attempt.time_spent_seconds or "",
            attempt.completed_at.isoformat() if attempt.completed_at else "",
        ])

    return output.getvalue()
