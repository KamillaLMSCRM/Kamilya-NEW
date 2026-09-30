"""Student dashboard service"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.models.courses import Course
from app.models.enrollment import Enrollment
from app.models.progress import Progress
from app.modules.certificates.models import Certificate
from app.modules.enrollments.context import current_enrollment, scoped_enrollment_id
from app.modules.enrollments.occurrences import is_current_occurrence
from app.modules.learning_cycles.read_model import join_cycle_read_model
from app.modules.lessons.models import Lesson, Module


def _resume_progress_scope(
    enrollment_scopes: list[tuple[UUID, UUID, UUID | None]],
    *,
    enrollment_id_column: ColumnElement[Any],
    course_id_column: ColumnElement[Any],
    progress_enrollment_id_column: ColumnElement[Any],
) -> ColumnElement[bool]:
    """Correlate each progress key to its own enrollment and course row."""
    return or_(
        *(
            and_(
                enrollment_id_column == enrollment_id,
                course_id_column == course_id,
                progress_enrollment_id_column == progress_enrollment_id,
            )
            for enrollment_id, course_id, progress_enrollment_id in enrollment_scopes
        )
    )


async def get_student_dashboard(
    db: AsyncSession,
    user_id: UUID,
    tenant_id: UUID,
    *,
    enrollment_id: UUID | None = None,
) -> dict[str, Any]:
    """Get student dashboard data.

    Optimization (audit §5.2): replaced N+1 (2 queries per enrolled
    course — one for total lessons, one for completed) with a single
    grouped query that returns (course_id, total_lessons,
    completed_lessons) for ALL enrolled courses in one round-trip.
    """
    # Get enrolled courses
    enrollment_query = (
        select(Enrollment, Course)
        .join(Course, Enrollment.course_id == Course.id)
        .where(
            Enrollment.user_id == user_id,
            Enrollment.tenant_id == tenant_id,
            Course.tenant_id == tenant_id,
            Course.status == "published",
        )
        .order_by(
            case((Enrollment.status.in_(("enrolled", "in_progress")), 0), else_=1),
            Enrollment.enrolled_at.desc(),
            Enrollment.id.desc(),
        )
    )
    if enrollment_id is not None:
        enrollment_query = enrollment_query.where(Enrollment.id == enrollment_id)
    else:
        enrollment_query = enrollment_query.where(
            Enrollment.status.notin_(("cancelled", "superseded")),
            is_current_occurrence(),
        )
    enrollment_query, cycle = join_cycle_read_model(enrollment_query, tenant_id)
    enrollment_query = enrollment_query.add_columns(cycle.assignment_due_at)
    enrollments_result = await db.execute(enrollment_query)
    enrollments = enrollments_result.all()

    # The existing player resolves one delivery occurrence per course. Match
    # its selection policy here; assignment-scoped identities stay exact.
    can_resume_by_enrollment: dict[UUID, bool] = {}
    if enrollment_id is not None:
        # An exact personal-link read does not imply that every player endpoint
        # can write against that occurrence. Fail closed if its resolver differs.
        for enrollment, course, _due in enrollments:
            delivery = await current_enrollment(db, tenant_id=tenant_id, user_id=user_id, course_id=course.id)
            can_resume_by_enrollment[enrollment.id] = delivery is not None and delivery.id == enrollment.id
    else:
        canonical_by_course: dict[UUID, UUID] = {}
        for enrollment, course, _due in enrollments:
            if enrollment.status not in ("enrolled", "in_progress", "completed"):
                continue
            canonical_by_course.setdefault(course.id, enrollment.id)
        can_resume_by_enrollment = {
            enrollment.id: canonical_by_course.get(course.id) == enrollment.id
            for enrollment, course, _due in enrollments
        }

    enrolled_course_ids = [course.id for _e, course, _due_at in enrollments]

    # Single grouped query: total + completed lessons per course.
    # LEFT JOIN to include courses with 0 lessons (still enrolled).
    totals_by_course: dict[UUID, tuple[int, int]] = {}
    completed_by_instance: dict[tuple[UUID, UUID | None], int] = {}
    if enrolled_course_ids:
        # Total lessons per course (one row per course).
        totals_query = (
            select(Module.course_id, func.count(Lesson.id).label("total"))
            .join(Lesson, Lesson.module_id == Module.id)
            .where(Module.course_id.in_(enrolled_course_ids))
            .where(Module.tenant_id == tenant_id, Lesson.tenant_id == tenant_id)
            .group_by(Module.course_id)
        )
        for totals_row in (await db.execute(totals_query)).all():
            totals_by_course[totals_row.course_id] = (totals_row.total, 0)

        # Completed lessons per course.
        completed_query = (
            select(Module.course_id, Progress.enrollment_id, func.count(Progress.id).label("completed"))
            .join(Lesson, Lesson.module_id == Module.id)
            .join(Progress, Progress.lesson_id == Lesson.id)
            .where(
                Module.course_id.in_(enrolled_course_ids),
                Progress.user_id == user_id,
                Progress.tenant_id == tenant_id,
                Progress.course_id == Module.course_id,
                Progress.completed,
                Module.tenant_id == tenant_id,
                Lesson.tenant_id == tenant_id,
            )
            .group_by(Module.course_id, Progress.enrollment_id)
        )
        for completed_row in (await db.execute(completed_query)).all():
            completed_by_instance[(completed_row.course_id, completed_row.enrollment_id)] = completed_row.completed

    # Read unfinished native lessons for all current enrollments in one query.
    # NULL enrollment scope is retained only for legacy manual assignments.
    resume_by_enrollment: dict[UUID, str] = {}
    resumable_enrollments = [
        (enrollment, course, due_at)
        for enrollment, course, due_at in enrollments
        if can_resume_by_enrollment.get(enrollment.id, False)
    ]
    if resumable_enrollments:
        progress_scope = _resume_progress_scope(
            [
                (enrollment.id, course.id, scoped_enrollment_id(enrollment))
                for enrollment, course, _due_at in resumable_enrollments
            ],
            enrollment_id_column=Enrollment.id,
            course_id_column=Module.course_id,
            progress_enrollment_id_column=Progress.enrollment_id,
        )
        resume_query = (
            select(Enrollment.id, Lesson.id, Progress.completed, Progress.last_accessed_at)
            .join(Course, Course.id == Enrollment.course_id)
            .join(Module, and_(Module.course_id == Course.id, Module.tenant_id == tenant_id))
            .join(Lesson, and_(Lesson.module_id == Module.id, Lesson.tenant_id == tenant_id))
            .outerjoin(
                Progress,
                and_(
                    Progress.lesson_id == Lesson.id,
                    Progress.course_id == Course.id,
                    Progress.tenant_id == tenant_id,
                    Progress.user_id == user_id,
                    progress_scope,
                ),
            )
            .where(
                Enrollment.id.in_([enrollment.id for enrollment, _course, _due in resumable_enrollments]),
                Enrollment.tenant_id == tenant_id,
                Enrollment.user_id == user_id,
                Course.tenant_id == tenant_id,
            )
            .order_by(Module.order_index, Lesson.order_index, Module.id, Lesson.id)
        )
        candidates_by_enrollment: dict[UUID, list[tuple[UUID, datetime | None]]] = {}
        for enrollment_id, lesson_id, completed, last_accessed_at in (await db.execute(resume_query)).all():
            if not completed:
                candidates_by_enrollment.setdefault(enrollment_id, []).append((lesson_id, last_accessed_at))
        delivery_by_enrollment = {
            enrollment.id: getattr(course, "delivery_type", "native")
            for enrollment, course, _due_at in resumable_enrollments
        }
        for enrollment_id, candidates in candidates_by_enrollment.items():
            if delivery_by_enrollment.get(enrollment_id) == "scorm" or not candidates:
                continue
            recent: list[tuple[UUID, datetime]] = [
                (lesson_id, last_accessed_at)
                for lesson_id, last_accessed_at in candidates
                if last_accessed_at is not None
            ]
            chosen = max(recent, key=lambda candidate: candidate[1].timestamp()) if recent else candidates[0]
            resume_by_enrollment[enrollment_id] = f"?lessonId={chosen[0]}"

    enrolled_courses = []
    total_lessons_all = 0
    completed_lessons_all = 0

    for enrollment, course, assignment_due_at in enrollments:
        if getattr(course, "delivery_type", "native") == "scorm":
            total_lessons, completed_lessons = 1, 1 if enrollment.status == "completed" else 0
            progress_percent = 100 if enrollment.status == "completed" else 0
        else:
            total_lessons = totals_by_course.get(course.id, [0, 0])[0]
            progress_key = scoped_enrollment_id(enrollment)
            completed_lessons = completed_by_instance.get((course.id, progress_key), 0)
            progress_percent = round((completed_lessons / total_lessons * 100) if total_lessons > 0 else 0)

        enrolled_courses.append(
            {
                "enrollment_id": enrollment.id,
                "course_id": course.id,
                "title": course.title,
                "description": course.description or "",
                "status": course.status,
                "enrollment_status": enrollment.status,
                "can_resume": can_resume_by_enrollment.get(enrollment.id, False),
                "delivery_type": getattr(course, "delivery_type", "native"),
                "progress_percent": progress_percent,
                "total_lessons": total_lessons,
                "completed_lessons": completed_lessons,
                "enrolled_at": enrollment.enrolled_at,
                "last_accessed_at": None,
                "thumbnail_url": course.thumbnail_url,
                "assignment_due_at": assignment_due_at,
                "assignment_source": getattr(enrollment, "source", None),
                "resume_href": (
                    f"/courses/{course.id}{resume_by_enrollment.get(enrollment.id, '')}"
                    if can_resume_by_enrollment.get(enrollment.id, False)
                    else None
                ),
            }
        )

        total_lessons_all += total_lessons
        completed_lessons_all += completed_lessons

    # Count certificates
    certificate_query = select(func.count(Certificate.id)).where(
        Certificate.user_id == user_id,
        Certificate.tenant_id == tenant_id,
    )
    if enrollment_id is not None:
        certificate_query = certificate_query.where(Certificate.enrollment_id == enrollment_id)
    cert_count_result = await db.execute(certificate_query)
    certificates_count = cert_count_result.scalar() or 0

    total_progress = round((completed_lessons_all / total_lessons_all * 100) if total_lessons_all > 0 else 0)
    completed_courses = sum(1 for c in enrolled_courses if c["enrollment_status"] == "completed")

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
    db: AsyncSession,
    user_id: UUID,
    course_id: UUID,
    tenant_id: UUID,
) -> dict[str, Any] | None:
    """Get detailed course progress with modules and lessons."""
    course = await db.get(Course, course_id)
    if not course:
        return None

    enrollment = await current_enrollment(db, tenant_id=tenant_id, user_id=user_id, course_id=course_id)
    progress_enrollment_id = scoped_enrollment_id(enrollment)
    # Get modules
    modules_result = await db.execute(select(Module).where(Module.course_id == course_id).order_by(Module.order_index))
    modules = modules_result.scalars().all()

    modules_progress = []
    for module in modules:
        lessons_result = await db.execute(
            select(Lesson).where(Lesson.module_id == module.id).order_by(Lesson.order_index)
        )
        lessons = lessons_result.scalars().all()

        lessons_progress = []
        for lesson in lessons:
            progress_result = await db.execute(
                select(Progress).where(
                    Progress.user_id == user_id,
                    Progress.lesson_id == lesson.id,
                    Progress.tenant_id == tenant_id,
                    Progress.enrollment_id == progress_enrollment_id,
                )
            )
            progress = progress_result.scalar_one_or_none()

            lessons_progress.append(
                {
                    "lesson_id": lesson.id,
                    "title": lesson.title,
                    "completed": progress.completed if progress else False,
                    "progress_percent": progress.completion_percent if progress else 0,
                }
            )

        modules_progress.append(
            {
                "module_id": module.id,
                "title": module.title,
                "lessons": lessons_progress,
            }
        )

    return {
        "course_id": course.id,
        "title": course.title,
        "modules": modules_progress,
    }
