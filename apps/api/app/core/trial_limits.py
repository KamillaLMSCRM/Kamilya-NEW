"""Trial-plan limits for real self-service tenants.

This is separate from ``demo_limits``. The demo sandbox is a shared
prospect environment; trial tenants are real company tenants created via
``/tenants/register`` and must enforce billing limits server-side.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenants import Tenant, TenantUsage


TrialResource = Literal["courses", "ai_courses", "jd_courses", "learners", "system_users"]


RESOURCE_LABELS = {
    "courses": "курсов",
    "ai_courses": "AI-курсов",
    "jd_courses": "курсов по ДИ",
    "learners": "обучающихся",
    "system_users": "пользователей системы",
}


@dataclass(frozen=True)
class TrialLimits:
    ai_course_generations_limit: int | None = None
    jd_course_generations_limit: int | None = None
    max_students: int | None = None
    system_users_limit: int | None = None
    max_courses_total: int | None = None


class TrialLimitExceeded(HTTPException):
    def __init__(self, resource: TrialResource, limit: int, current: int, requested: int = 1):
        label = RESOURCE_LABELS.get(resource, resource)
        message = (
            f"Trial-лимит: {current}/{limit} {label}. "
            "Чтобы продолжить, обратитесь к суперадмину или перейдите на платный тариф."
        )
        payload = {
            "code": "trial_limit_exceeded",
            "resource": resource,
            "limit": limit,
            "current": current,
            "requested": requested,
            "message": message,
            "cta": {"text": "Связаться с Kamilya LMS", "href": "mailto:support@kml.kz"},
        }
        super().__init__(status_code=403, detail=payload)


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _is_trial_tenant(tenant: Tenant | None) -> bool:
    if not tenant:
        return False
    return tenant.plan == "trial" or tenant.status == "trial"


def _limits_from_tenant(tenant: Tenant) -> TrialLimits:
    settings = tenant.settings or {}
    raw = settings.get("trial_limits") or {}
    ai_limit = _as_int(raw.get("ai_course_generations_limit"))
    jd_limit = _as_int(raw.get("jd_course_generations_limit"))
    max_courses_total = _as_int(tenant.max_courses_per_month)
    if max_courses_total is None and (ai_limit is not None or jd_limit is not None):
        max_courses_total = int(ai_limit or 0) + int(jd_limit or 0)
    return TrialLimits(
        ai_course_generations_limit=ai_limit,
        jd_course_generations_limit=jd_limit,
        max_students=_as_int(raw.get("max_students")) or _as_int(tenant.max_users),
        system_users_limit=_as_int(raw.get("system_users_limit")),
        max_courses_total=max_courses_total,
    )


async def _get_trial_limits(db: AsyncSession, tenant_id: Any) -> TrialLimits | None:
    if tenant_id is None:
        return None
    tenant = await db.get(Tenant, tenant_id)
    if not _is_trial_tenant(tenant):
        return None
    return _limits_from_tenant(tenant)


async def count_courses(db: AsyncSession, tenant_id: Any) -> int:
    from app.models.courses import Course

    return int(
        await db.scalar(select(func.count(Course.id)).where(Course.tenant_id == tenant_id))
        or 0
    )


async def count_ai_courses(db: AsyncSession, tenant_id: Any) -> int:
    from app.models.courses import Course

    return int(
        await db.scalar(
            select(func.count(Course.id)).where(
                Course.tenant_id == tenant_id,
                Course.ai_generated == True,  # noqa: E712
            )
        )
        or 0
    )


async def count_active_students(db: AsyncSession, tenant_id: Any) -> int:
    from app.models.users import User

    return int(
        await db.scalar(
            select(func.count(User.id)).where(
                User.tenant_id == tenant_id,
                User.is_active == True,  # noqa: E712
                User.role == "student",
            )
        )
        or 0
    )


async def count_active_system_users(db: AsyncSession, tenant_id: Any) -> int:
    from app.models.users import User

    return int(
        await db.scalar(
            select(func.count(User.id)).where(
                User.tenant_id == tenant_id,
                User.is_active == True,  # noqa: E712
                User.role.in_(("admin", "org_admin", "teacher", "methodologist")),
            )
        )
        or 0
    )


async def assert_can_create_courses(db: AsyncSession, tenant_id: Any, requested: int = 1) -> None:
    limits = await _get_trial_limits(db, tenant_id)
    if not limits or limits.max_courses_total is None:
        return
    current = await count_courses(db, tenant_id)
    if current + requested > limits.max_courses_total:
        raise TrialLimitExceeded("courses", limits.max_courses_total, current, requested)


async def assert_can_create_ai_course(db: AsyncSession, tenant_id: Any, requested: int = 1) -> None:
    limits = await _get_trial_limits(db, tenant_id)
    if not limits:
        return
    await assert_can_create_courses(db, tenant_id, requested)
    if limits.ai_course_generations_limit is None:
        return
    current = await count_ai_courses(db, tenant_id)
    usage = await db.get(TenantUsage, tenant_id)
    if usage:
        current = max(current, int(usage.ai_course_generations_used or 0))
    if current + requested > limits.ai_course_generations_limit:
        raise TrialLimitExceeded("ai_courses", limits.ai_course_generations_limit, current, requested)


async def reserve_ai_course_generation(db: AsyncSession, tenant_id: Any) -> None:
    limits = await _get_trial_limits(db, tenant_id)
    if not limits:
        return
    await assert_can_create_ai_course(db, tenant_id, 1)
    usage = await db.get(TenantUsage, tenant_id)
    if not usage:
        usage = TenantUsage(tenant_id=tenant_id)
        db.add(usage)
        await db.flush()
    usage.ai_course_generations_used = int(usage.ai_course_generations_used or 0) + 1
    await db.flush()


async def assert_can_create_learners(db: AsyncSession, tenant_id: Any, requested: int = 1) -> None:
    limits = await _get_trial_limits(db, tenant_id)
    if not limits or limits.max_students is None:
        return
    current = await count_active_students(db, tenant_id)
    if current + requested > limits.max_students:
        raise TrialLimitExceeded("learners", limits.max_students, current, requested)


async def assert_can_create_system_users(db: AsyncSession, tenant_id: Any, requested: int = 1) -> None:
    limits = await _get_trial_limits(db, tenant_id)
    if not limits or limits.system_users_limit is None:
        return
    current = await count_active_system_users(db, tenant_id)
    if current + requested > limits.system_users_limit:
        raise TrialLimitExceeded("system_users", limits.system_users_limit, current, requested)
