"""Admin dashboard service"""
from uuid import UUID
from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc

from app.models.users import User
from app.models.courses import Course
from app.models.enrollment import Enrollment
from app.models.progress import Progress
from app.models.document import Document
from app.modules.certificates.models import Certificate
from app.modules.quizzes.models import QuizAttempt


async def get_tenant_stats(db: AsyncSession, tenant_id: UUID) -> dict:
    """Get comprehensive tenant statistics."""
    # Users
    total_users_result = await db.execute(
        select(func.count(User.id)).where(User.tenant_id == tenant_id)
    )
    total_users = total_users_result.scalar() or 0

    active_users_result = await db.execute(
        select(func.count(User.id)).where(User.tenant_id == tenant_id, User.is_active == True)
    )
    active_users = active_users_result.scalar() or 0

    # Courses
    total_courses_result = await db.execute(
        select(func.count(Course.id)).where(Course.tenant_id == tenant_id)
    )
    total_courses = total_courses_result.scalar() or 0

    published_courses_result = await db.execute(
        select(func.count(Course.id)).where(Course.tenant_id == tenant_id, Course.status == "published")
    )
    published_courses = published_courses_result.scalar() or 0

    ai_generated_result = await db.execute(
        select(func.count(Course.id)).where(Course.tenant_id == tenant_id, Course.ai_generated == True)
    )
    ai_generated_courses = ai_generated_result.scalar() or 0

    # Enrollments
    total_enrollments_result = await db.execute(
        select(func.count(Enrollment.id)).where(Enrollment.tenant_id == tenant_id)
    )
    total_enrollments = total_enrollments_result.scalar() or 0

    completed_enrollments_result = await db.execute(
        select(func.count(Enrollment.id)).where(
            Enrollment.tenant_id == tenant_id, Enrollment.status == "completed"
        )
    )
    completed_enrollments = completed_enrollments_result.scalar() or 0

    # Quiz attempts
    quizzes_taken_result = await db.execute(
        select(func.count(QuizAttempt.id)).where(QuizAttempt.tenant_id == tenant_id)
    )
    quizzes_taken = quizzes_taken_result.scalar() or 0

    avg_score_result = await db.execute(
        select(func.avg(QuizAttempt.score_percent)).where(QuizAttempt.tenant_id == tenant_id)
    )
    average_quiz_score = round(avg_score_result.scalar() or 0, 1)

    # Certificates
    certs_result = await db.execute(
        select(func.count(Certificate.id)).where(Certificate.tenant_id == tenant_id)
    )
    certificates_issued = certs_result.scalar() or 0

    # Documents
    docs_result = await db.execute(
        select(func.count(Document.id)).where(Document.tenant_id == tenant_id)
    )
    documents_uploaded = docs_result.scalar() or 0

    # Storage (sum of document sizes)
    storage_result = await db.execute(
        select(func.sum(Document.size)).where(Document.tenant_id == tenant_id)
    )
    storage_used_bytes = storage_result.scalar() or 0

    return {
        "total_users": total_users,
        "active_users": active_users,
        "total_courses": total_courses,
        "published_courses": published_courses,
        "ai_generated_courses": ai_generated_courses,
        "total_enrollments": total_enrollments,
        "completed_enrollments": completed_enrollments,
        "total_quizzes_taken": quizzes_taken,
        "average_quiz_score": average_quiz_score,
        "certificates_issued": certificates_issued,
        "documents_uploaded": documents_uploaded,
        "storage_used_bytes": storage_used_bytes,
    }


async def get_recent_users(db: AsyncSession, tenant_id: UUID, limit: int = 10) -> list:
    """Get recent users."""
    result = await db.execute(
        select(User)
        .where(User.tenant_id == tenant_id)
        .order_by(desc(User.created_at))
        .limit(limit)
    )
    return result.scalars().all()


async def get_recent_courses(db: AsyncSession, tenant_id: UUID, limit: int = 10) -> list:
    """Get recent courses with enrollment counts."""
    result = await db.execute(
        select(Course)
        .where(Course.tenant_id == tenant_id)
        .order_by(desc(Course.created_at))
        .limit(limit)
    )
    courses = result.scalars().all()

    course_list = []
    for course in courses:
        count_result = await db.execute(
            select(func.count(Enrollment.id)).where(Enrollment.course_id == course.id)
        )
        enrollment_count = count_result.scalar() or 0
        course_list.append({
            "id": course.id,
            "title": course.title,
            "status": course.status,
            "ai_generated": course.ai_generated,
            "created_by": course.created_by,
            "created_at": course.created_at,
            "published_at": course.published_at,
            "enrollment_count": enrollment_count,
        })

    return course_list


async def get_enrollment_by_course(db: AsyncSession, tenant_id: UUID) -> list:
    """Get enrollment stats per course."""
    courses_result = await db.execute(
        select(Course).where(Course.tenant_id == tenant_id).order_by(desc(Course.created_at))
    )
    courses = courses_result.scalars().all()

    stats = []
    for course in courses:
        enrolled_result = await db.execute(
            select(func.count(Enrollment.id)).where(Enrollment.course_id == course.id)
        )
        enrolled = enrolled_result.scalar() or 0

        completed_result = await db.execute(
            select(func.count(Enrollment.id)).where(
                Enrollment.course_id == course.id, Enrollment.status == "completed"
            )
        )
        completed = completed_result.scalar() or 0

        # Average progress
        progress_result = await db.execute(
            select(func.avg(Progress.completion_percent)).where(Progress.course_id == course.id)
        )
        avg_progress = round(progress_result.scalar() or 0, 1)

        stats.append({
            "course_id": course.id,
            "course_title": course.title,
            "total_enrolled": enrolled,
            "completed": completed,
            "in_progress": enrolled - completed,
            "not_started": 0,
            "average_progress": avg_progress,
        })

    return stats


async def get_activity_summary(db: AsyncSession, tenant_id: UUID, days: int = 30) -> list:
    """Get daily activity summary for the last N days."""
    activity = []
    for i in range(days):
        date = datetime.now(timezone.utc) - timedelta(days=i)
        day_start = date.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)

        new_users_result = await db.execute(
            select(func.count(User.id)).where(
                User.tenant_id == tenant_id,
                User.created_at >= day_start,
                User.created_at < day_end,
            )
        )
        new_users = new_users_result.scalar() or 0

        new_enrollments_result = await db.execute(
            select(func.count(Enrollment.id)).where(
                Enrollment.tenant_id == tenant_id,
                Enrollment.enrolled_at >= day_start,
                Enrollment.enrolled_at < day_end,
            )
        )
        new_enrollments = new_enrollments_result.scalar() or 0

        quizzes_result = await db.execute(
            select(func.count(QuizAttempt.id)).where(
                QuizAttempt.tenant_id == tenant_id,
                QuizAttempt.completed_at >= day_start,
                QuizAttempt.completed_at < day_end,
            )
        )
        quizzes_taken = quizzes_result.scalar() or 0

        certs_result = await db.execute(
            select(func.count(Certificate.id)).where(
                Certificate.tenant_id == tenant_id,
                Certificate.issued_at >= day_start,
                Certificate.issued_at < day_end,
            )
        )
        certs_issued = certs_result.scalar() or 0

        activity.append({
            "date": day_start.strftime("%Y-%m-%d"),
            "new_users": new_users,
            "new_enrollments": new_enrollments,
            "quizzes_taken": quizzes_taken,
            "certificates_issued": certs_issued,
        })

    return list(reversed(activity))


async def get_admin_dashboard(db: AsyncSession, tenant_id: UUID) -> dict:
    """Get complete admin dashboard data."""
    stats = await get_tenant_stats(db, tenant_id)
    recent_users = await get_recent_users(db, tenant_id)
    recent_courses = await get_recent_courses(db, tenant_id)
    enrollment_by_course = await get_enrollment_by_course(db, tenant_id)
    activity_summary = await get_activity_summary(db, tenant_id, days=30)

    return {
        "stats": stats,
        "recent_users": recent_users,
        "recent_courses": recent_courses,
        "enrollment_by_course": enrollment_by_course,
        "activity_summary": activity_summary,
    }
