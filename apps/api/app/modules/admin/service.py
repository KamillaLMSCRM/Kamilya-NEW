"""Admin dashboard service"""
from uuid import UUID
from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc

from app.models.users import User
from app.models.courses import Course
from app.models.tenants import Tenant, TenantUsage
from app.models.enrollment import Enrollment
from app.models.progress import Progress
from app.models.document import Document
from app.modules.certificates.models import Certificate
from app.modules.quizzes.models import QuizAttempt


def _usage_item(used: int, limit: int | None) -> dict:
    return {
        "used": used,
        "limit": limit,
        "remaining": None if limit is None else max(0, limit - used),
    }


async def get_trial_usage(db: AsyncSession, tenant_id: UUID) -> dict:
    tenant = await db.get(Tenant, tenant_id)
    if not tenant:
        raise ValueError("Tenant not found")

    limits = (tenant.settings or {}).get("trial_limits") or {}
    ai_limit = limits.get("ai_course_generations_limit")
    jd_limit = limits.get("jd_course_generations_limit")
    learners_limit = limits.get("max_students") or tenant.max_users
    system_users_limit = limits.get("system_users_limit")

    usage = await db.get(TenantUsage, tenant_id)

    ai_generated_courses = (
        await db.execute(
            select(func.count(Course.id)).where(
                Course.tenant_id == tenant_id,
                Course.ai_generated == True,
            )
        )
    ).scalar() or 0

    learner_roles = ("student",)
    learners_used = (
        await db.execute(
            select(func.count(User.id)).where(
                User.tenant_id == tenant_id,
                User.is_active == True,
                User.role.in_(learner_roles),
            )
        )
    ).scalar() or 0

    system_users_used = (
        await db.execute(
            select(func.count(User.id)).where(
                User.tenant_id == tenant_id,
                User.is_active == True,
                User.role.in_(("admin", "org_admin", "teacher", "methodologist")),
            )
        )
    ).scalar() or 0

    now = datetime.now(timezone.utc)
    days_left = None
    if tenant.trial_ends_at:
        end = tenant.trial_ends_at
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        days_left = max(0, (end - now).days)

    return {
        "plan": tenant.plan,
        "status": tenant.status,
        "trial_started_at": tenant.trial_started_at,
        "trial_ends_at": tenant.trial_ends_at,
        "days_left": days_left,
        "ai_courses": _usage_item(
            max(
                int((usage.ai_course_generations_used if usage else 0) or 0),
                int(ai_generated_courses or 0),
            ),
            ai_limit,
        ),
        "jd_courses": _usage_item(int((usage.jd_course_generations_used if usage else 0) or 0), jd_limit),
        "learners": _usage_item(int(learners_used), learners_limit),
        "system_users": _usage_item(int(system_users_used), system_users_limit),
    }


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
    """Get recent courses with enrollment counts (single query)."""
    result = await db.execute(
        select(
            Course,
            func.count(Enrollment.id).label("enrollment_count"),
        )
        .outerjoin(Enrollment, Enrollment.course_id == Course.id)
        .where(Course.tenant_id == tenant_id)
        .group_by(Course.id)
        .order_by(desc(Course.created_at))
        .limit(limit)
    )
    return [
        {
            "id": c.id,
            "title": c.title,
            "status": c.status,
            "ai_generated": c.ai_generated,
            "created_by": c.created_by,
            "created_at": c.created_at,
            "published_at": c.published_at,
            "enrollment_count": count,
        }
        for c, count in result.all()
    ]


async def get_enrollment_by_course(db: AsyncSession, tenant_id: UUID) -> list:
    """Get enrollment stats per course (single query)."""
    result = await db.execute(
        select(
            Course,
            func.count(Enrollment.id).label("total_enrolled"),
            func.count(
                func.nullif(Enrollment.status, "completed").__eq__(None)
            ).label("completed"),
            func.avg(Progress.completion_percent).label("avg_progress"),
        )
        .outerjoin(Enrollment, Enrollment.course_id == Course.id)
        .outerjoin(Progress, Progress.course_id == Course.id)
        .where(Course.tenant_id == tenant_id)
        .group_by(Course.id)
        .order_by(desc(Course.created_at))
    )

    stats = []
    for row in result.all():
        course = row[0]
        enrolled = row.total_enrolled or 0
        # Count completed enrollments with a subquery approach
        comp_result = await db.execute(
            select(func.count(Enrollment.id)).where(
                Enrollment.course_id == course.id,
                Enrollment.status == "completed",
            )
        )
        completed = comp_result.scalar() or 0

        stats.append({
            "course_id": course.id,
            "course_title": course.title,
            "total_enrolled": enrolled,
            "completed": completed,
            "in_progress": enrolled - completed,
            "not_started": 0,
            "average_progress": round(row.avg_progress or 0, 1),
        })
    return stats


async def get_activity_summary(db: AsyncSession, tenant_id: UUID, days: int = 30) -> list:
    """Get daily activity summary for the last N days (single query with date_trunc)."""
    activity = []
    for i in range(days):
        date = datetime.now(timezone.utc) - timedelta(days=i)
        day_start = date.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)

        # Batch: single query with CASE for each metric
        from sqlalchemy import case
        result = await db.execute(
            select(
                func.count(User.id).label("new_users"),
                func.count(Enrollment.id).label("new_enrollments"),
                func.count(QuizAttempt.id).label("quizzes_taken"),
                func.count(Certificate.id).label("certs_issued"),
            )
            .select_from(
                select(User.id.label("uid")).where(
                    User.tenant_id == tenant_id,
                    User.created_at >= day_start,
                    User.created_at < day_end,
                ).subquery()
            )
            .crossjoin(
                select(Enrollment.id.label("eid")).where(
                    Enrollment.tenant_id == tenant_id,
                    Enrollment.enrolled_at >= day_start,
                    Enrollment.enrolled_at < day_end,
                ).subquery()
            )
            .crossjoin(
                select(QuizAttempt.id.label("qid")).where(
                    QuizAttempt.tenant_id == tenant_id,
                    QuizAttempt.completed_at >= day_start,
                    QuizAttempt.completed_at < day_end,
                ).subquery()
            )
            .crossjoin(
                select(Certificate.id.label("cid")).where(
                    Certificate.tenant_id == tenant_id,
                    Certificate.issued_at >= day_start,
                    Certificate.issued_at < day_end,
                ).subquery()
            )
        )
        row = result.one()
        activity.append({
            "date": day_start.strftime("%Y-%m-%d"),
            "new_users": row.new_users or 0,
            "new_enrollments": row.new_enrollments or 0,
            "quizzes_taken": row.quizzes_taken or 0,
            "certificates_issued": row.certs_issued or 0,
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
