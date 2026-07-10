"""Onboarding status service — compute step flags from existing tables.

Single SQL per count (7 short queries, all indexed). The queries are
intentionally simple: we don't need sub-millisecond because this
endpoint is called once per page load (admin dashboard) and the rows
are tiny for a fresh tenant.

Tenant scope is enforced via `tenant_id` parameter from the JWT.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.onboarding.schemas import OnboardingStatus, OnboardingStep


async def _count(db: AsyncSession, stmt) -> int:
    """Run a count statement and return int."""
    return int((await db.execute(stmt)).scalar() or 0)


async def compute_onboarding_status(
    db: AsyncSession,
    tenant_id: UUID,
) -> OnboardingStatus:
    """Compute the 7-step onboarding status for a tenant.

    Each step queries an existing table. We tolerate missing rows
    (e.g. tenant_settings not yet seeded) by treating them as "not done".
    """
    from app.models.courses import Course
    from app.models.department import Department
    from app.models.document import Document
    from app.models.enrollment import Enrollment
    from app.models.kiosk_link import KioskLink
    from app.models.tenant_settings import TenantSettings
    from app.models.tenants import Tenant
    from app.models.user_roles import UserRole  # for invitations count
    from app.models.users import User, UserInvitation

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
            trial_ends_at = tenant.trial_ends_at.isoformat()
            now = datetime.now(timezone.utc)
            delta = tenant.trial_ends_at - now
            trial_days_remaining = max(0, delta.days)

    # Active users (tenant scope, status='active')
    active_users = await _count(
        db,
        select(func.count(User.id)).where(
            User.tenant_id == tenant_id,
            User.status == "active",
            User.is_active.is_(True),
        ),
    )

    # 1) Profile complete — tenant has settings row, with logo_url or primary_color
    settings = await db.get(TenantSettings, tenant_id)
    profile_done = (
        tenant is not None
        and settings is not None
        and (settings.logo_url or "").strip() != ""
        and (settings.primary_color or "").strip() != ""
    )

    # 2) Staff imported — at least 2 active users (1 admin + 1 staff)
    staff_imported = active_users >= 2

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

    # 6) Kiosk or invitation — at least 1 kiosk OR at least 1 pending invitation
    kiosks_count = await _count(
        db,
        select(func.count(KioskLink.id)).where(KioskLink.tenant_id == tenant_id),
    )
    pending_invites = await _count(
        db,
        select(func.count(UserInvitation.id)).where(
            UserInvitation.tenant_id == tenant_id,
            UserInvitation.status == "pending",
        ),
    )
    kiosk_or_invite_done = kiosks_count > 0 or pending_invites > 0

    # 7) Training log — "viewed" is not trackable without a click log,
    # so we mark this done when there is at least 1 enrollment (admin
    # will naturally check the journal when staff starts learning).
    training_log_done = enrollments_count > 0

    steps: list[OnboardingStep] = [
        OnboardingStep(
            id="profile",
            label="Заполнить профиль компании (логотип, цвет)",
            done=profile_done,
            href="/admin/settings",
            badge=None if profile_done else "опционально",
        ),
        OnboardingStep(
            id="staff_import",
            label="Импортировать штат",
            done=staff_imported,
            href="/staff?tab=import",
            badge=f"{active_users} сотр." if active_users else None,
        ),
        OnboardingStep(
            id="documents",
            label="Загрузить документы (ДИ, регламенты)",
            done=documents_done,
            href="/documents",
            badge=f"{documents_count} док." if documents_count else None,
        ),
        OnboardingStep(
            id="first_course",
            label="Сгенерировать первый курс (AI из документов)",
            done=first_course_done,
            href="/ai/generate",
            badge=f"{courses_count} курс." if courses_count else None,
        ),
        OnboardingStep(
            id="first_assignment",
            label="Назначить курс сотрудникам",
            done=first_assignment_done,
            href="/assignments",
            badge=f"{enrollments_count} назн." if enrollments_count else None,
        ),
        OnboardingStep(
            id="kiosk_or_invite",
            label="Создать киоск или разослать приглашения",
            done=kiosk_or_invite_done,
            href="/admin/kiosks",
            badge=f"{kiosks_count} киоск / {pending_invites} пригл." if (kiosks_count or pending_invites) else None,
        ),
        OnboardingStep(
            id="training_log",
            label="Проверить журнал обучения",
            done=training_log_done,
            href="/admin/training-log",
            badge=None,
        ),
    ]

    completed = all(s.done for s in steps)

    return OnboardingStatus(
        steps=steps,
        completed=completed,
        trial_ends_at=trial_ends_at,
        trial_days_remaining=trial_days_remaining,
        plan=plan,
        max_users=max_users,
        active_users=active_users,
    )