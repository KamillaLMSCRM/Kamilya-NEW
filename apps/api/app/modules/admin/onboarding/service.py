"""Onboarding status service — compute step flags from existing tables.

Single SQL per count (6 short queries, all indexed). The queries are
intentionally simple: we don't need sub-millisecond because this
endpoint is called once per page load (admin dashboard) and the rows
are tiny for a fresh tenant.

Tenant scope is enforced via `tenant_id` parameter from the JWT.
"""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.onboarding.schemas import OnboardingStatus, OnboardingStep


async def _count(db: AsyncSession, stmt) -> int:
    """Run a count statement and return int."""
    return int((await db.execute(stmt)).scalar() or 0)


async def compute_onboarding_status(
    db: AsyncSession,
    tenant_id: UUID,
    role: str | None = None,
) -> OnboardingStatus:
    """Compute the role-specific onboarding status for a tenant.

    Each step queries an existing table. We tolerate missing rows
    (e.g. tenant_settings not yet seeded) by treating them as "not done".
    """
    from app.models.courses import Course
    from app.models.document import Document
    from app.models.enrollment import Enrollment
    from app.models.tenants import Tenant
    from app.models.users import User

    # Tenant + trial info
    tenant = await db.get(Tenant, tenant_id)
    trial_ends_at: str | None = None
    trial_days_remaining: int | None = None
    plan: str | None = None
    max_users: int | None = None
    if tenant is not None:
        plan = tenant.plan
        max_users = tenant.max_users
        if tenant.trial_ends_at is not None:
            trial_end = tenant.trial_ends_at
            if trial_end.tzinfo is None:
                trial_end = trial_end.replace(tzinfo=UTC)
            trial_ends_at = trial_end.isoformat()
            now = datetime.now(UTC)
            delta = trial_end - now
            trial_days_remaining = max(0, delta.days)

    trial_state = "not_trial"
    if tenant is not None and (tenant.plan == "trial" or tenant.status == "trial"):
        trial_state = "active"
        if trial_ends_at is not None:
            if trial_end <= datetime.now(UTC):
                trial_state = "expired"
            elif trial_days_remaining is not None and trial_days_remaining <= 3:
                trial_state = "nearing_expiry"
            else:
                trial_state = "active"

    # Active users (tenant scope, status='active')
    active_users = await _count(
        db,
        select(func.count(User.id)).where(
            User.tenant_id == tenant_id,
            User.status == "active",
            User.is_active.is_(True),
        ),
    )

    # 1) Team ready — both tenant governance roles are present and active.
    admin_count = await _count(
        db,
        select(func.count(User.id)).where(
            User.tenant_id == tenant_id,
            User.status == "active",
            User.is_active.is_(True),
            User.role == "admin",
        ),
    )
    methodologist_count = await _count(
        db,
        select(func.count(User.id)).where(
            User.tenant_id == tenant_id,
            User.status == "active",
            User.is_active.is_(True),
            User.role == "methodologist",
        ),
    )
    system_users_count = admin_count + methodologist_count

    # 2) Staff imported — system users do not count as learners.
    learners_count = await _count(
        db,
        select(func.count(User.id)).where(
            User.tenant_id == tenant_id,
            User.status == "active",
            User.is_active.is_(True),
            User.role == "student",
        ),
    )
    staff_imported = learners_count > 0

    # 3) Documents uploaded — at least 1 document for this tenant
    documents_count = await _count(
        db,
        select(func.count(Document.id)).where(Document.tenant_id == tenant_id),
    )
    documents_done = documents_count > 0

    # 4) First course generated
    courses_count = await _count(
        db,
        select(func.count(Course.id)).where(Course.tenant_id == tenant_id),
    )
    first_course_done = courses_count > 0

    # 5) First course assigned — at least 1 enrollment
    enrollments_count = await _count(
        db,
        select(func.count(Enrollment.id)).where(Enrollment.tenant_id == tenant_id),
    )
    first_assignment_done = enrollments_count > 0

    # 6) Training log — only real learning completion makes this step done.
    completed_enrollments_count = await _count(
        db,
        select(func.count(Enrollment.id)).where(
            Enrollment.tenant_id == tenant_id,
            or_(
                Enrollment.status == "completed",
                Enrollment.completed_at.is_not(None),
            ),
        ),
    )
    training_log_done = completed_enrollments_count > 0

    steps: list[OnboardingStep] = [
        OnboardingStep(
            id="team",
            label="Добавить администратора и методолога",
            done=admin_count > 0 and methodologist_count > 0,
            href="/admin/team",
            badge=f"{system_users_count} польз." if system_users_count else None,
            owner="admin",
        ),
        OnboardingStep(
            id="staff_import",
            label="Импортировать штат",
            done=staff_imported,
            href="/staff?tab=import",
            badge=f"{learners_count} сотр." if learners_count else None,
            owner="methodologist",
        ),
        OnboardingStep(
            id="documents",
            label="Загрузить документы (ДИ, регламенты)",
            done=documents_done,
            href="/documents",
            badge=f"{documents_count} док." if documents_count else None,
            owner="methodologist",
        ),
        OnboardingStep(
            id="first_course",
            label="Сгенерировать первый курс (AI из документов)",
            done=first_course_done,
            href="/ai/generate",
            badge=f"{courses_count} курс." if courses_count else None,
            owner="methodologist",
        ),
        OnboardingStep(
            id="first_assignment",
            label="Открыть опубликованный курс и назначить сотрудникам",
            done=first_assignment_done,
            href="/courses",
            badge=f"{enrollments_count} назн." if enrollments_count else None,
            owner="methodologist",
        ),
        OnboardingStep(
            id="training_log",
            label="Проверить журнал обучения",
            done=training_log_done,
            href="/training-log",
            badge=f"{completed_enrollments_count} заверш." if completed_enrollments_count else None,
            owner="methodologist",
        ),
    ]

    trial_usage: dict[str, dict[str, int | None]] = {}
    trial_exhausted_limits: list[str] = []
    trial_access_state = "not_applicable"
    if tenant is not None and (tenant.plan == "trial" or tenant.status == "trial"):
        from app.modules.admin.service import get_trial_usage

        usage = await get_trial_usage(db, tenant_id)
        for resource in ("ai_courses", "jd_courses", "learners", "system_users"):
            item = usage.get(resource) or {}
            snapshot = {
                "used": int(item.get("used") or 0),
                "limit": item.get("limit"),
                "remaining": item.get("remaining"),
            }
            trial_usage[resource] = snapshot
            if snapshot["limit"] is not None and snapshot["remaining"] == 0:
                trial_exhausted_limits.append(resource)
        trial_access_state = (
            "support_required"
            if trial_state == "expired"
            else "limited"
            if trial_state == "nearing_expiry" or trial_exhausted_limits
            else "available"
        )

    if role in {"admin", "methodologist"}:
        steps = [step for step in steps if step.owner == role]
    completed = all(s.done for s in steps)

    return OnboardingStatus(
        steps=steps,
        completed=completed,
        trial_ends_at=trial_ends_at,
        trial_days_remaining=trial_days_remaining,
        plan=plan,
        max_users=max_users,
        active_users=active_users,
        role=role if role in {"admin", "methodologist", "superadmin"} else None,
        trial_state=trial_state,
        trial_access_state=trial_access_state,
        trial_exhausted_limits=trial_exhausted_limits,
        trial_usage=trial_usage,
    )
