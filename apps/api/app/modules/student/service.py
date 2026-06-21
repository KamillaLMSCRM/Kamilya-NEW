"""Student dashboard service"""
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.models.courses import Course
from app.modules.lessons.models import Module, Lesson
from app.models.enrollment import Enrollment
from app.models.progress import Progress
from app.modules.certificates.models import Certificate


async def get_student_dashboard(db: AsyncSession, user_id: UUID, tenant_id: UUID) -> dict:
    """Get student dashboard data."""
    # Get enrolled courses
    enrollments_result = await db.execute(
        select(Enrollment, Course)
        .join(Course, Enrollment.course_id == Course.id)
        .where(Enrollment.user_id == user_id, Enrollment.tenant_id == tenant_id)
        .order_by(Enrollment.enrolled_at.desc())
    )
    enrollments = enrollments_result.all()

    enrolled_courses = []
    total_lessons_all = 0
    completed_lessons_all = 0

    for enrollment, course in enrollments:
        # Get total lessons in course
        total_result = await db.execute(
            select(func.count(Lesson.id))
            .join(Module, Lesson.module_id == Module.id)
            .where(Module.course_id == course.id)
        )
        total_lessons = total_result.scalar() or 0

        # Get completed lessons for user
        completed_result = await db.execute(
            select(func.count(Progress.id))
            .join(Lesson, Progress.lesson_id == Lesson.id)
            .join(Module, Lesson.module_id == Module.id)
            .where(
                Module.course_id == course.id,
                Progress.user_id == user_id,
                Progress.completed == True,
            )
        )
        completed_lessons = completed_result.scalar() or 0

        progress_percent = round((completed_lessons / total_lessons * 100) if total_lessons > 0 else 0)

        enrolled_courses.append({
            "course_id": course.id,
            "title": course.title,
            "description": course.description or "",
            "status": course.status,
            "progress_percent": progress_percent,
            "total_lessons": total_lessons,
            "completed_lessons": completed_lessons,
            "enrolled_at": enrollment.enrolled_at,
            "last_accessed_at": None,
            "thumbnail_url": course.thumbnail_url,
        })

        total_lessons_all += total_lessons
        completed_lessons_all += completed_lessons

    # Count certificates
    cert_count_result = await db.execute(
        select(func.count(Certificate.id)).where(
            Certificate.user_id == user_id,
            Certificate.tenant_id == tenant_id,
        )
    )
    certificates_count = cert_count_result.scalar() or 0

    total_progress = round((completed_lessons_all / total_lessons_all * 100) if total_lessons_all > 0 else 0)
    completed_courses = sum(1 for c in enrolled_courses if c["progress_percent"] == 100)

    return {
        "user_id": user_id,
        "full_name": "",
        "enrolled_courses": enrolled_courses,
        "total_courses": len(enrolled_courses),
        "completed_courses": completed_courses,
        "total_progress_percent": total_progress,
        "certificates_count": certificates_count,
        "recent_activity": [],
    }


async def get_course_progress_detail(
    db: AsyncSession, user_id: UUID, course_id: UUID, tenant_id: UUID
) -> dict:
    """Get detailed course progress with modules and lessons."""
    course = await db.get(Course, course_id)
    if not course:
        return None

    # Get modules
    modules_result = await db.execute(
        select(Module)
        .where(Module.course_id == course_id)
        .order_by(Module.order_index)
    )
    modules = modules_result.scalars().all()

    modules_progress = []
    for module in modules:
        lessons_result = await db.execute(
            select(Lesson)
            .where(Lesson.module_id == module.id)
            .order_by(Lesson.order_index)
        )
        lessons = lessons_result.scalars().all()

        lessons_progress = []
        for lesson in lessons:
            progress_result = await db.execute(
                select(Progress).where(
                    Progress.user_id == user_id,
                    Progress.lesson_id == lesson.id,
                    Progress.tenant_id == tenant_id,
                )
            )
            progress = progress_result.scalar_one_or_none()

            lessons_progress.append({
                "lesson_id": lesson.id,
                "title": lesson.title,
                "completed": progress.completed if progress else False,
                "progress_percent": progress.completion_percent if progress else 0,
            })

        modules_progress.append({
            "module_id": module.id,
            "title": module.title,
            "lessons": lessons_progress,
        })

    return {
        "course_id": course.id,
        "title": course.title,
        "modules": modules_progress,
    }
